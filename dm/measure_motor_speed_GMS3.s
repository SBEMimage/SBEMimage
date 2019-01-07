// $BACKGROUND$
// Script to measure motor speeds in GMS3

number counter
number timer, timeElapsed

// Move both motors to the origin position (0, 0)
EMSetStageX(0)
while (abs(EMGetStageX()-0) > 0.010){ // expect 10 nm precision
	timeElapsed = (GetCurrentTime() - timer) / 10000000
	if (timeElapsed > 30){
		Throw ("Motor X did not reach origin.")
	}
}

EMSetStageY(0)
while (abs(EMGetStageY()-0) > 0.010){
	timeElapsed = (GetCurrentTime() - timer) / 10000000
	if (timeElapsed > 30){
		Throw ("Motor Y did not reach origin.")
	}
}

result(DateStamp() + ": Started (Motor X).\n")

for (counter=1; counter<=10; counter++) {
	EMSetStageX(50)
	timer = GetCurrentTime()
	while (abs(EMGetStageX()-50) > 0.010){
		timeElapsed = (GetCurrentTime()-timer)/10000000
		if (timeElapsed > 10){
			Throw ("Motor X did not reach target position of 50.")
		}
	}
	EMSetStageX(0)
	timer = GetCurrentTime()
	while (abs(EMGetStageX()-0) > 0.010){
		timeElapsed = (GetCurrentTime()-timer)/10000000
		if (timeElapsed > 10){
			Throw ("Motor X did not reach target position of 0.")
		}
	}	
}

result(DateStamp() + ": Stopped (Motor X).\n")

result(DateStamp() + ": Started (Motor Y).\n")

for (counter=1; counter<=10; counter++) {
	EMSetStageY(50)
	timer = GetCurrentTime()
	while (abs(EMGetStageY()-50) > 0.010){
		timeElapsed = (GetCurrentTime()-timer)/10000000
		if (timeElapsed > 10){
			Throw ("Motor Y did not reach target position of 50.")
		}
	}
	EMSetStageY(0)
	timer = GetCurrentTime()
	while (abs(EMGetStageY()-0) > 0.010){
		timeElapsed = (GetCurrentTime()-timer)/10000000
		if (timeElapsed > 10){
			Throw ("Motor X did not reach target position of 0.")
		}
	}	
}

result(DateStamp() + ": Stopped (Motor Y).\n")