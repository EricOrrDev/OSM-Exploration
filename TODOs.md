# TODOS

The Audio portion of the system could have an account login to save routes (use OAuth for google and apple)

Will NOT be an app, ideally would be extension of large navigation software like google maps or apple maps.

## For Audio
- Find and notify truncated domes (Done just make it more clear)
- Buttons
- Bike lanes
- Other miscellaneous features

## On Categorizing Intersections into Tiles
Criteria to categorize new intersections
 - How many roads meet
   - Mid block (crossing not at an intersection)
   - ‘T’
   - Cross
   - Offset ‘Y’ (angled ‘T’)
   - Offset cross (angled)
   - Roundabout
 - Number of lanes
 - Protected median
   - Includes islands
 - Other features will be added via audio - crosswalk buttons

Will the audio be on the web or its own app
Don't want it to be an app ideally - potentially plugin

Possible test groups to identify proper tile scale and tactile language - timeframe
Local users who would be willing to test
Aim to find others as well

Each Step X output should put out a parsable output, somewhat like JSON, in that we parse out the content for the screen reader from the attributes at each step, like [Curve : Curve left 45 degrees 20 meters] which would become something like Continue forward along a gentle curve which curves 45 degrees to your left over 10 paces. 

Maximum 50 tiles per book (preferably 20-30)