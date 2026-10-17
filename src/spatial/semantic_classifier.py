"""Semantic Road & Driveway Disambiguation Engine for Blind Pedestrian Crossings."""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Tuple


class SemanticCrossingType(str, Enum):
    PUBLIC_STREET = "public_street"
    COMMERCIAL_DRIVEWAY = "commercial_driveway"
    PRIVATE_DRIVEWAY = "private_driveway"
    PARKING_LOT_ACCESS = "parking_lot_access"
    SERVICE_ALLEY = "service_alley"
    INTERNAL_CAMPUS = "internal_campus"
    UNKNOWN_CROSSING = "unknown_crossing"


@dataclass
class DisambiguationResult:
    """Classified semantic metadata for a pedestrian crossing corridor."""
    crossing_type: SemanticCrossingType
    canonical_name: str
    spoken_road_name: str
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    raw_name: Optional[str] = None
    turning_vehicle_warning: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


# Well-known commercial retail / business entities in municipal surveyor shorthand
COMMERCIAL_BRANDS: List[str] = [
    "SAFEWAY",
    "FRED MEYER",
    "STARBUCKS",
    "MCDONALDS",
    "MCDONALD'S",
    "WALMART",
    "TARGET",
    "CHEVRON",
    "SCHWAB",
    "HOME DEPOT",
    "COSTCO",
    "WINCO",
    "ALBERTSONS",
    "BI-MART",
    "DUTCH BROS",
    "TRADER JOE",
    "TACO BELL",
    "WENDYS",
    "WENDY'S",
    "SUBWAY",
    "WALGREENS",
    "RITE AID",
    "LOWES",
    "LOWE'S",
    "BEST BUY",
    "PANDA EXPRESS",
    "CHIPOTLE",
    "MARKET OF CHOICE",
    "NEWPORT MARKET",
    "SPORTSMAN",
]

# Municipal abbreviations for major City of Bend thoroughfares
BEND_KNOWN_THOROUGHFARES: Dict[str, str] = {
    "CENTUR": "SW Century Drive",
    "CENTURY": "SW Century Drive",
    "SIMPSO": "SW Simpson Avenue",
    "SIMPSON": "SW Simpson Avenue",
    "CHANDL": "SW Chandler Avenue",
    "CHANDLER": "SW Chandler Avenue",
    "COLORA": "SW Colorado Avenue",
    "COLORADO": "SW Colorado Avenue",
    "DAVENO": "NW Davenport Avenue",
    "DAVENPORT": "NW Davenport Avenue",
    "COLLEG": "SW College Way",
    "COLLEGE": "SW College Way",
    "MTWASH": "NW Mount Washington Drive",
    "MT WASHINGTON": "NW Mount Washington Drive",
    "REEDMK": "SE Reed Market Road",
    "REED MARKET": "SE Reed Market Road",
    "SHIELD": "SW Shevlin Hixon Drive",
    "SHEVLIN HIXON": "SW Shevlin Hixon Drive",
    "EMPIRE": "NW Empire Avenue",
    "PORTLA": "NW Portland Avenue",
    "PORTLAND": "NW Portland Avenue",
    "NEWPOR": "NW Newport Avenue",
    "NEWPORT": "NW Newport Avenue",
    "GREENW": "NE Greenwood Avenue",
    "GREENWOOD": "NE Greenwood Avenue",
    "BEARCR": "SE Bear Creek Road",
    "BEAR CREEK": "SE Bear Creek Road",
    "BOND": "NW Bond Street",
    "WALL": "NW Wall Street",
    "GALVES": "NW Galveston Avenue",
    "GALVESTON": "NW Galveston Avenue",
    "TAYLOR": "SW Innovation Way",  # Renamed from SW Taylor Court by Bend City Council Res. 3403
    "TAYLR": "SW Innovation Way",
    "INNOVATION": "SW Innovation Way",
    "DONOVA": "SW Donovan Avenue",
    "DONOVAN": "SW Donovan Avenue",
    "14TH": "NW 14th Street",
    "14TH NW": "NW 14th Street",
    "15TH": "SW 15th Street",
    "27TH": "NE 27th Street",
    "3RD": "SE 3rd Street",
    "3RDSE": "SE 3rd Street",
}


class SemanticRoadClassifier:
    """
    Arbitrates multi-source geospatial data (Municipal GIS + OSM + geometric attributes)
    to accurately distinguish dedicated public streets from commercial driveways,
    parking lot entrances, and private access roads.
    """

    def classify(
        self,
        raw_name: Optional[str] = None,
        municipal_owner: Optional[str] = None,
        municipal_street_class: Optional[str] = None,
        osm_tags: Optional[Dict[str, str]] = None,
        crossing_width_m: Optional[float] = None,
    ) -> DisambiguationResult:
        """
        Classify crossing corridor into semantic category with canonical names and spoken form.
        """
        tags = osm_tags or {}

        # 1. Check OSM highway / service tags first if available
        highway_tag = tags.get("highway")
        service_tag = tags.get("service")

        if highway_tag == "service":
            if service_tag == "driveway":
                canonical = self._format_driveway_name(raw_name) or "private driveway"
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PRIVATE_DRIVEWAY,
                    canonical_name=canonical,
                    spoken_road_name=f"the {canonical}" if not canonical.lower().startswith("the ") else canonical,
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=False,
                )
            elif service_tag in ("parking_aisle", "parking"):
                canonical = self._format_commercial_name(raw_name) or "parking lot access"
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PARKING_LOT_ACCESS,
                    canonical_name=canonical,
                    spoken_road_name=f"the {canonical}" if not canonical.lower().startswith("the ") else canonical,
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                )
            elif service_tag == "alley":
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.SERVICE_ALLEY,
                    canonical_name="service alley",
                    spoken_road_name="the service alley",
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=False,
                )

        # 2. Analyze raw name (from curb ramp / crosswalk attributes)
        if raw_name:
            name_cleaned = raw_name.strip()
            # Handle surveyor "MAINSTREET - CROSSSTREET" patterns like "CENTURY - SAFEWAY DRIVE"
            if " - " in name_cleaned:
                parts = name_cleaned.split(" - ")
                # Use the secondary component representing the crossed cut
                name_cleaned = parts[-1].strip()

            upper = name_cleaned.upper()

            # Rule A: Commercial Brand Detection (e.g. SAFEWAY, FRED MEYER)
            brand = self._match_commercial_brand(upper)
            if brand:
                canonical, spoken = self._resolve_commercial_brand_driveway(upper, brand)
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.COMMERCIAL_DRIVEWAY,
                    canonical_name=canonical,
                    spoken_road_name=spoken,
                    confidence="HIGH" if municipal_street_class in ("A", "Private") else "MEDIUM",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                    details={"brand": brand},
                )

            # Rule B: Keyword triggers (DRIVEWAY, ENTRANCE, ACCESS, LOT, ALLEY, FIRE STATION)
            if "FIRE STATION" in upper:
                if "NORTH" in upper or " N " in upper or "N SIDE" in upper:
                    name = "Fire Station north driveway"
                elif "SOUTH" in upper or " S " in upper or "S SIDE" in upper:
                    name = "Fire Station south driveway"
                else:
                    name = "Fire Station driveway"
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.COMMERCIAL_DRIVEWAY,
                    canonical_name=name,
                    spoken_road_name=f"the {name}",
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                )

            if "ALLEY" in upper:
                if upper in ("TIN PAN ALLEY",):
                    name = "Tin Pan Alley"
                    spoken = "Tin Pan Alley"
                else:
                    name = self._expand_title_name(name_cleaned)
                    spoken = f"the {name}" if not name.lower().startswith("the ") else name
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.SERVICE_ALLEY,
                    canonical_name=name,
                    spoken_road_name=spoken,
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=False,
                )

            if "LOT" in upper or "PARKING" in upper:
                name = self._expand_title_name(name_cleaned)
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PARKING_LOT_ACCESS,
                    canonical_name=name,
                    spoken_road_name=f"the {name}",
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                )

            if "DRIVEWAY" in upper or "ENTRANCE" in upper or "ACCESS" in upper or "APRON" in upper:
                name = self._expand_title_name(name_cleaned)
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.COMMERCIAL_DRIVEWAY if ("COMMERCE" in upper or "SCHWAB" in upper or "MALL" in upper) else SemanticCrossingType.PRIVATE_DRIVEWAY,
                    canonical_name=name,
                    spoken_road_name=f"the {name}",
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                )

            if upper in ("PRIVATE", "PRIVATE DRIVEWAY", "PRIVATE ROAD"):
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PRIVATE_DRIVEWAY,
                    canonical_name="private driveway",
                    spoken_road_name="the private driveway",
                    confidence="HIGH",
                    raw_name=raw_name,
                    turning_vehicle_warning=False,
                )

            # Rule C: Municipal Owner / StreetClass check
            is_private_muni = (municipal_owner and municipal_owner.upper() in ("PRIVATE",)) or (
                municipal_street_class and municipal_street_class.upper() in ("A", "PRIVATE")
            )

            # Rule D: Known public thoroughfares (stripping municipal segment digits like CENTUR040 -> CENTUR)
            base_upper = re.sub(r"\d+$", "", upper).strip()
            for prefix, full_st in BEND_KNOWN_THOROUGHFARES.items():
                if (
                    upper == prefix
                    or upper.startswith(prefix + " ")
                    or upper.endswith(" " + prefix)
                    or base_upper == prefix
                    or base_upper.startswith(prefix + " ")
                    or base_upper.endswith(" " + prefix)
                ):
                    # If municipal record explicitly says StreetClass 'A' (Alley/Access) and not a primary street
                    if is_private_muni and not any(k in upper or k in base_upper for k in ("CENTUR", "SIMPSO", "TAYL", "CHANDL", "COLORA", "DONOV")):
                        return DisambiguationResult(
                            crossing_type=SemanticCrossingType.COMMERCIAL_DRIVEWAY,
                            canonical_name=f"{full_st} access",
                            spoken_road_name=f"the {full_st} access",
                            confidence="MEDIUM",
                            raw_name=raw_name,
                            turning_vehicle_warning=True,
                        )
                    return DisambiguationResult(
                        crossing_type=SemanticCrossingType.PUBLIC_STREET,
                        canonical_name=full_st,
                        spoken_road_name=full_st,
                        confidence="HIGH",
                        raw_name=raw_name,
                        turning_vehicle_warning=False,
                    )

            # Rule E: General Title-cased Street Name
            expanded = self._expand_title_name(name_cleaned)
            if is_private_muni:
                canonical = f"{expanded} private entrance"
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PRIVATE_DRIVEWAY,
                    canonical_name=canonical,
                    spoken_road_name=f"the {canonical}",
                    confidence="MEDIUM",
                    raw_name=raw_name,
                    turning_vehicle_warning=True,
                )

            return DisambiguationResult(
                crossing_type=SemanticCrossingType.PUBLIC_STREET,
                canonical_name=expanded,
                spoken_road_name=expanded,
                confidence="MEDIUM",
                raw_name=raw_name,
                turning_vehicle_warning=False,
            )

        # 3. Fallback when name is None or missing
        if crossing_width_m is not None:
            if crossing_width_m < 6.0:
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.COMMERCIAL_DRIVEWAY,
                    canonical_name="commercial driveway",
                    spoken_road_name="the commercial driveway",
                    confidence="LOW",
                    raw_name=None,
                    turning_vehicle_warning=True,
                    details={"inferred_from": "crossing_width < 6m"},
                )
            else:
                return DisambiguationResult(
                    crossing_type=SemanticCrossingType.PUBLIC_STREET,
                    canonical_name="side street",
                    spoken_road_name="the street",
                    confidence="LOW",
                    raw_name=None,
                    turning_vehicle_warning=False,
                    details={"inferred_from": "crossing_width >= 6m"},
                )

        # 4. Ultimate unknown fallback
        return DisambiguationResult(
            crossing_type=SemanticCrossingType.UNKNOWN_CROSSING,
            canonical_name="street crossing",
            spoken_road_name="the street",
            confidence="LOW",
            raw_name=None,
            turning_vehicle_warning=False,
        )

    def _match_commercial_brand(self, upper_text: str) -> Optional[str]:
        """Detect whether text contains a known commercial brand."""
        for brand in COMMERCIAL_BRANDS:
            # Check whole word match
            pattern = rf"\b{re.escape(brand)}\b"
            if re.search(pattern, upper_text):
                return brand
        return None

    def _resolve_commercial_brand_driveway(self, upper: str, brand: str) -> Tuple[str, str]:
        """
        Transforms surveyor shorthand like 'SAFEWAY DRIVE' or 'S SAFEWAY DR'
        into 'Safeway commercial driveway' and 'the Safeway commercial driveway'.
        """
        title_brand = brand.title() if "'" not in brand else brand.capitalize()

        is_south = upper.startswith("S ") or upper.startswith("SOUTH ") or " S " in upper
        is_north = upper.startswith("N ") or upper.startswith("NORTH ") or " N " in upper
        is_east = upper.startswith("E ") or upper.startswith("EAST ")
        is_west = upper.startswith("W ") or upper.startswith("WEST ")

        prefix = ""
        if is_south:
            prefix = "South "
        elif is_north:
            prefix = "North "
        elif is_east:
            prefix = "East "
        elif is_west:
            prefix = "West "

        if "ENTRANCE" in upper:
            canonical = f"{prefix}{title_brand} store entrance".strip()
        elif "LOT" in upper or "PARKING" in upper:
            canonical = f"{prefix}{title_brand} parking lot entrance".strip()
        elif "DRIVEWAY" in upper:
            canonical = f"{prefix}{title_brand} driveway".strip()
        else:
            # Replaces 'SAFEWAY DRIVE' / 'S SAFEWAY DR' -> 'Safeway commercial driveway'
            canonical = f"{prefix}{title_brand} commercial driveway".strip()

        spoken = f"the {canonical}"
        return canonical, spoken

    def _format_commercial_name(self, raw_name: Optional[str]) -> Optional[str]:
        if not raw_name:
            return None
        upper = raw_name.upper()
        brand = self._match_commercial_brand(upper)
        if brand:
            canonical, _ = self._resolve_commercial_brand_driveway(upper, brand)
            return canonical
        return self._expand_title_name(raw_name)

    def _format_driveway_name(self, raw_name: Optional[str]) -> Optional[str]:
        if not raw_name:
            return None
        return self._expand_title_name(raw_name)

    def _expand_title_name(self, raw: str) -> str:
        """Expand abbreviations (DR -> Drive, ST -> Street, etc.) and title-case."""
        words = raw.strip().split()
        expanded: List[str] = []
        for w in words:
            w_up = w.upper()
            if w_up == "DR":
                expanded.append("Drive")
            elif w_up in ("ST", "STR"):
                expanded.append("Street")
            elif w_up in ("AVE", "AV"):
                expanded.append("Avenue")
            elif w_up == "RD":
                expanded.append("Road")
            elif w_up == "BLVD":
                expanded.append("Boulevard")
            elif w_up == "LN":
                expanded.append("Lane")
            elif w_up == "CT":
                expanded.append("Court")
            elif w_up in ("WY", "WAY"):
                expanded.append("Way")
            elif w_up == "S":
                expanded.append("South")
            elif w_up == "N":
                expanded.append("North")
            elif w_up == "E":
                expanded.append("East")
            elif w_up == "W":
                expanded.append("West")
            elif w_up in ("SW", "NW", "SE", "NE"):
                expanded.append(w_up)
            else:
                expanded.append(w.capitalize())
        return " ".join(expanded)
