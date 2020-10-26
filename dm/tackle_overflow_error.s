// $BACKGROUND$
//
// The following procedure solves the "positive overflow error" that 
// occasionally comes up in DM2:
//     1) Manually start the standard record sequence in DM for one 
//        cycle with the correct knife cut and retract speeds.
//     2) Pause the scanning (which starts automatically when cut completed). 
//     3) Near the knife (Uncheck the "Clear Knife" checkbox). 
//     4) Run this script to execute the function MicrotomeStage_Cut(0),
//        see below. (Click on "Execute".)
//     5) Change the "0" to "1", and run this script to execute 
//        the function MicrotomeStage_Cut(1)
//     6) Clear the knife.

MicrotomeStage_Cut(0)
