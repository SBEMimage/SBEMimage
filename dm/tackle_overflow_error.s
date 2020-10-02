// $BACKGROUND$
//
// The following procedure solves the "positive overflow error" that 
// occasionally comes up in DM2:
//     1) Run the standard record sequence in DM for one cycle
//	   2) Near the knife
//	   3) Run this script to execute the function MicrotomeStage_Cut(0)
//	   4) Run this script to execute the function MicrotomeStage_Cut(1)
//	   5) Clear the knife

MicrotomeStage_Cut(0)
