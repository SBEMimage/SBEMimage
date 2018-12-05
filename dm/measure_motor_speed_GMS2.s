// $BACKGROUND$
// Script to measure motor speeds in GMS2

number counter
// Move both motors to the origin position (0, 0)
MicrotomeStage_SetPositionX(0, 1)
MicrotomeStage_SetPositionY(0, 1)

result(DateStamp() + ": Started (Motor X).\n")

for (counter=1; counter<=10; counter++) {
	MicrotomeStage_SetPositionX(50, 1)
	MicrotomeStage_SetPositionX(0, 1)
}

result(DateStamp() + ": Stopped (Motor X).\n")

result(DateStamp() + ": Started (Motor Y).\n")

for (counter=1; counter<=10; counter++) {
	MicrotomeStage_SetPositionY(50, 1)
	MicrotomeStage_SetPositionY(0, 1)
}

result(DateStamp() + ": Stopped (Motor Y).\n")