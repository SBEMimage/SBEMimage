// $BACKGROUND$
//
// The "BACKGROUND" command above is not a comment. It is required for this
// script to work properly.
//
// ========================================================================
//   This Gatan DigitalMicrograph script is part of SBEMimage, ver. 2.0,
//   3View/SmartSEM acquisition control software
//   (c) 2016-2018 Benjamin Titze,
//   Friedrich Miescher Institute for Biomedical Research, Basel.
//   This software is licensed under the terms of the MIT License.
//   See LICENSE.txt in the project rool folder.
//
//   This script (SBEMimage_DMcom_GMS3.s) must be running in DM to enable
//   communication between SBEMimage and 3View. It is compatible with
//   GMS 3. Another version is available for GMS 2.
// ========================================================================
//
// INSTRUCTIONS FOR USERS:
//
// If your SBEMimage installation is not in C:\pytools\SBEMimage, you must
// change the install_path variable in line 599 before using this script.
//
// After opening this script (SBEMimage_DMcom_GMS3.s), click "Execute".
// Then start SBEMimage.
// The script's activity is recorded in DM's output window.
// After starting the script, the text in the output window should say:
// "Ready. Waiting for command from SBEMimage..."
// To open the output window: Menu "Window" -> Show Output Window
//
// If DM crashes or behaves eratically, restart DM and restart this script.
// If the script becomes unresponsive, for example after a DM error
// message, restart it by clicking "Execute" again.
// If DM shows a "positive overflow" error message during a cut, run the
// script "tackle_overflow_error.s" in "\SBEMimage\dm".
// If the knife moves with the wrong speed during a cut, execute one full
// record cycle from within DM with the intended knife speed.


string install_path
string trigger_file
string command_file
string error_file
string return_file
string acknowledge_file
string acknowledge_file_cut
string warning_file

string command
string set_value_str

number cmd_status
number file
number err_file
number timer
number time_elapsed
number get_value
number get_valueX
number get_valueY
number set_value1
number set_value2
number t_status
number idle_counter
number idle_threshold
number success
number readok
number createok
number remote_control
number stroke_down
number oscillator_off
number cut_ok
number near_ok
number clear_ok
number DS_value
number currentX
number currentY
number currentZ

number move_duration
number move_duration_x
number move_duration_y
number motor_speed_x
number motor_speed_y


void wait_for_command()
{
	// Check whether trigger file exists. If yes, read command
	// file. Command file contains one command string, and (optionally)
    // up to two float parameters.
    if (DoesFileExist(trigger_file))
    {
		idle_counter = 0
        idle_threshold = 1
        Result(DateStamp() + ": Triggered! Reading command file...\n" )
        // Delete err/ack/wng files:
		if (DoesFileExist(error_file)) {
			DeleteFile(error_file)
		}
		if (DoesFileExist(acknowledge_file)) {
			DeleteFile(acknowledge_file)
		}
		if (DoesFileExist(acknowledge_file_cut)) {
			DeleteFile(acknowledge_file_cut)
		}
		if (DoesFileExist(warning_file)) {
			DeleteFile(warning_file)
		}
		readok = 0
		try {
			if (DoesFileExist(command_file)) {
				file = OpenFileForReading(command_file)
				readok = 1
			}
		}
		catch {
			result(DateStamp() + ": ERROR occured when trying to open command file.\n")
			sleep(2)
			err_file = CreateFileForWriting(error_file)
			closefile(err_file)
		}
		try {
			if (readok) {
				cmd_status = ReadFileLine(file, command)
				cmd_status = ReadFileLine(file, set_value_str)
				set_value1 = val(set_value_str)
				cmd_status = ReadFileLine(file, set_value_str)
				set_value2 = val(set_value_str)
				closefile(file)
				result(DateStamp() + ": Command received: " + command)
			}
		}
		catch {
			result(DateStamp() + ": ERROR occured when trying to read command file.\n")
			sleep(2)
			err_file = CreateFileForWriting(error_file)
			closefile(err_file)
		}
        // ================================================================
		if (command == "Handshake") {
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to open return file.\n")
				sleep(2)
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
			try {
				if (createok) {
					WriteFile(file, "OK")
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to write to return file.\n")
				sleep(2)
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_Cut") {
			// Only for testing purposes. Limited error handling.
			// Stroke up, oscillator on:
			stroke_down = 0
		    oscillator_off = 0
		    DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
		    DSSetDigitalOutput(DS_value)
            sleep(1)
		    // Cut:
			if (!MicrotomeStage_Cut(1)) {
				sleep(2)
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
				result("\n" + DateStamp() + ": ERROR cutting the sample.\n")
			}
			sleep(1)
			result("\n" + DateStamp() + ": Done.\n")
		    // Stroke down, oscillator off:
			stroke_down = 1
		    oscillator_off = 1
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
		    DSSetDigitalOutput(DS_value)
            sleep(1)
		}
		// ================================================================
		if (command == "MicrotomeStage_Retract") {
			// Only for testing purposes. No error handling.
			MicrotomeStage_Retract(1)
			result("\n" + DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_Clear") {
			// Clear the knife, with error handling.
			clear_ok = 1
            MicrotomeStage_Clear()
	        timer = GetCurrentTime()
	        while (MicrotomeStage_GetClearMotorState() != 3) {
		        sleep(0.1)
                time_elapsed = (GetCurrentTime()-timer)/10000000
		        if (time_elapsed > 4){
			        clear_ok = 0
                    file = CreateFileForWriting(error_file)
				    closefile(file)
				    result(DateStamp() + ": ERROR clearing the knife.\n")
		        }
	        }
			if (clear_ok) {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result("\n" + DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_Near") {
			// Near the knife, with error handling.
            near_ok = 1
            MicrotomeStage_Near()
          	timer = GetCurrentTime()
	        while (MicrotomeStage_GetClearMotorState() != 1) {
		        sleep(0.1)
                time_elapsed = (GetCurrentTime()-timer)/10000000
		        if (time_elapsed > 4) {
                    near_ok = 0
		     		file = CreateFileForWriting(error_file)
			    	closefile(file)
				    result(DateStamp() + ": ERROR nearing the knife.\n")
			    }
            }
			if (near_ok) {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result("\n" + DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_FullCut") {
		    // Perform a full cutting cycle with error handling.
			// This function is called during a stack acquisition.
			// Duration of one cycle (cut speed: 0.3, retract speed: 0.9):
			// ~15 s
			result("\n" + DateStamp() + ": =========================================.\n")
		    result(DateStamp() + ": Full cutting cycle in progress.\n")
		    cut_ok = 1
            // Near knife:
            MicrotomeStage_Near()
          	timer = GetCurrentTime()
	        while (MicrotomeStage_GetClearMotorState() != 1) {
	            sleep(0.1)
		        time_elapsed = (GetCurrentTime()-timer)/10000000
		        if (time_elapsed > 4) {
                    cut_ok = 0
		     		file = CreateFileForWriting(error_file)
			    	closefile(file)
				    result(DateStamp() + ": ERROR nearing the knife.\n")
			    }
            }
			sleep(2)
			// Stroke up, oscillator on:
			stroke_down = 0
			oscillator_off = 0
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Cut:
			if (!MicrotomeStage_Cut(1)) {
				sleep(2)
				cut_ok = 0
				file = CreateFileForWriting(error_file)
				closefile(file)
				result(DateStamp() + ": ERROR cutting the sample.\n")
			}
			sleep(1)
			// Stroke down, oscillator off:
			stroke_down = 1
			oscillator_off = 1
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Retract knife:
			if (!MicrotomeStage_Retract(1)) {
				sleep(2)
				cut_ok = 0
				file = CreateFileForWriting(error_file)
				closefile(file)
				result(DateStamp() + ": ERROR retracting the knife.\n")
			}
			// Clear knife:
            MicrotomeStage_Clear()
	        timer = GetCurrentTime()
	        while (MicrotomeStage_GetClearMotorState() != 3) {
		        sleep(0.1)
                time_elapsed = (GetCurrentTime()-timer)/10000000
		        if (time_elapsed > 4){
			        cut_ok = 0
                    file = CreateFileForWriting(error_file)
				    closefile(file)
				    result(DateStamp() + ": ERROR clearing the knife.\n")
		        }
	        }
			sleep(2)
			if (cut_ok) {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file_cut)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_FullApproachCut") {
			// Perform cut cycle without near/clear, with error handling.
			// This function is called from the approach dialog.
			// Duration of one cycle (cut speed: 0.3, retract speed: 0.9):
			// ~9 s
			result("\n" + DateStamp() + ": =========================================.\n")
		    result(DateStamp() + ": Approach cutting cycle in progress.\n")
		    cut_ok = 1
			// Stroke up, oscillator on:
			stroke_down = 0
			oscillator_off = 0
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Cut:
			if (!MicrotomeStage_Cut(1)) {
				sleep(2)
				cut_ok = 0
				file = CreateFileForWriting(error_file)
				closefile(file)
				result(DateStamp() + ": ERROR cutting the sample.\n")
			}
			sleep(1)
			// Stroke down, oscillator off:
			stroke_down = 1
			oscillator_off = 1
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Retract knife:
			if (!MicrotomeStage_Retract(1)) {
				sleep(2)
				cut_ok = 0
				file = CreateFileForWriting(error_file)
				closefile(file)
				result(DateStamp() + ": ERROR retracting the knife.\n")
			}
			if (cut_ok) {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file_cut)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionX") {
			get_value = EMGetStageX()
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to open return file.\n")
			}
			try {
				if (createok) {
					WriteFile(file, format(get_value, "%9.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionY") {
		    get_value = EMGetStageY()
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to open return file.\n")
			}
			try {
				if (createok) {
					WriteFile(file, format(get_value, "%9.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionXY") {
		    get_valueX = EMGetStageX()
		    get_valueY = EMGetStageY()
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to open return file.\n")
			}
			try {
				if (createok) {
					WriteFile(file, format(get_valueX, "%9.3f") + "\n" + format(get_valueY, "%9.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionZ") {
		    get_value = EMGetStageZ()
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to open return file.\n")
			}
			try {
				if (createok) {
					WriteFile(file, format(get_value, "%9.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occured when trying to write to return file.")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionX\n") {
			result(DateStamp() + ": set_value: " + set_value1)
			EMSetStageX(set_value1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionY\n") {
		    result(DateStamp() + ": set_value: " + set_value1)
			EMSetStageY(set_value1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionXY\n") {
			// Set XY position:
			result(DateStamp() + ": set_value_X: " + set_value1 + "\n")
			result(DateStamp() + ": set_value_Y: " + set_value2 + "\n")
			EMSetStageX(set_value1)
			EMSetStageY(set_value2)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionXY_Confirm\n") {
			// Set XY position, read XY position after move, and check
            // if target coordinates reached. If not, try again.
			// If second attempt fails, write coordinates to return file
			// and create error file.
			// This function is called during stack acquisitions.
			result(DateStamp() + ": set_value_X: " + set_value1 + "\n")
			result(DateStamp() + ": set_value_Y: " + set_value2 + "\n")
			// Get current coordinates:
			currentX = EMGetStageX()
			currentY = EMGetStageY()
			// Calculate how long the intended move will take:
			move_duration_x = abs(currentX - set_value1) / motor_speed_x
			move_duration_y = abs(currentY - set_value2) / motor_speed_y
			if (move_duration_x > move_duration_y) {
				move_duration = move_duration_x
			}
			else {
				move_duration = move_duration_y
			}
			// Motors will move simultaneously:
			EMSetStageX(set_value1)
			EMSetStageY(set_value2)
			// Wait until target position reached:
			result("\n" + DateStamp() + ": Wait for move: " + move_duration + "\n")
			sleep(move_duration + 0.2)
			// Get new coordinates:
			currentX = EMGetStageX()
			currentY = EMGetStageY()
			// Check if the current position does NOT match the target
			// position within 50 nm:
			if ((abs(currentX - set_value1) > 0.05) || (abs(currentY - set_value2) > 0.05)) {
				// Create warning file and try again after 2 seconds:
				file = CreateFileForWriting(warning_file)
				closefile(file)
				result("\n" + DateStamp() + ": WARNING - stage XY target coordinates mismatch.\n")
				sleep(2)
				// Read current stage coordinates and check again:
				currentX = EMGetStageX()
				currentY = EMGetStageY()
				if ((abs(currentX - set_value1) > 0.05) || (abs(currentY - set_value2) > 0.05)) {
					// Create error file. Write current position into
					// return file:
					file = CreateFileForWriting(error_file)
					closefile(file)
					file = CreateFileForWriting(return_file)
					WriteFile(file, format(currentX, "%9.3f") + "\n" + format(currentY, "%9.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": ERROR - stage XY target coordinates not reached.\n")
				}
				else {
					// Create acknowledge file:
					file = CreateFileForWriting(acknowledge_file)
					closefile(file)
					result(DateStamp() + ": Done.\n")
				}
			}
			else {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionZ\n") {
		    result(DateStamp() + ": set_value: " + set_value1 + "\n")
			EMSetStageZ(set_value1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionZ_Confirm\n") {
			// Set Z position, read new Z position after move, and check
			// if target Z was reached.
			// If not, write Z coordinate to return file and create
			// error file.
			// This function is called during stack acquisitions.
		    result(DateStamp() + ": set_value: " + set_value1 + "\n")
			// Move:
			EMSetStageZ(set_value1)
            sleep(0.5)
			// Get new Z position:
			currentZ = EMGetStageZ()
			// Check if the current position does NOT match the target
			// position within 5 nm:
			if (abs(currentZ - set_value1) > 0.005) {
				// Create error file. Write current position into
				// return file:
				file = CreateFileForWriting(error_file)
				closefile(file)
				file = CreateFileForWriting(return_file)
				WriteFile(file, format(currentZ, "%9.3f"))
				closefile(file)
				result("\n" + DateStamp() + ": ERROR - stage Z target position not reached.\n")
			}
			else {
				// Create acknowledge file:
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "SetMotorSpeedCalibrationXY\n") {
			// Set motor speed calibration values:
			motor_speed_x = set_value1
			motor_speed_y = set_value2
			result(DateStamp() + ": motor_speed_x: " + motor_speed_x + "\n")
			result(DateStamp() + ": motor_speed_y: " + motor_speed_y + "\n")
			// Create acknowledge file:
			file = CreateFileForWriting(acknowledge_file)
			closefile(file)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "Stop") {
			remote_control = 0
			result("\n" + DateStamp() + ": Script stopped.\n\n")
			createok = 0
			try {
				file = CreateFileForWriting(return_file)
				createok = 1
			}
			catch {
				result(DateStamp() + ": ERROR occured when trying to open return file.\n")
			}
			try {
				if (createok) {
					WriteFile(file, "END")
					closefile(file)
				}
			}
			catch {
				result(DateStamp() + ": ERROR occured when trying to write to return file.\n")
			}
		}
		DeleteFile(trigger_file)
		t_status = 0
    }
    else
    {
		if (t_status == 0) {
			Result(DateStamp() + ": Ready. Waiting for command from SBEMimage...\n" )
			t_status = 1
		}
	}
}

// ===== Script execution starts here =====

install_path = "C:\\pytools\\SBEMimage\\dm\\"
// This (empty) file triggers the communication:
trigger_file = install_path + "DMcom.trg"
// This file contains commands from SBEMimage:
command_file = install_path + "DMcom.in"
// This (empty) file is created to indicate that a command was executed:
acknowledge_file = install_path + "DMcom.ack"
// This (empty) file is created to indicate that a full cut was executed:
acknowledge_file_cut = install_path + "DMcom.ac2"
// This (empty) file is created to indicate a critical failure:
error_file = install_path + "DMcom.err"
// This file contains return value(s) to be read by SBEMimage:
return_file = install_path + "DMcom.out"
// This file signals a warning:
warning_file = install_path + "DMcom.wng"

number wait_interval = 0.1
remote_control = 1
// Default settings for motor speeds (slow), can be updated from SBEMimage:
motor_speed_x = 40
motor_speed_y = 40

if (!DoesFileExist(install_path + "SBEMimage_DMcom_GMS3.s")) {
	Throw("Wrong install path. Please check and update the variable 'install_path' in this script.")
}

result("\n" + DateStamp() + ": *******************************************.\n")
result(DateStamp() + ": SBEMimage DMcom script started...\n")

// Create empty command file:
file = CreateFileForWriting(command_file)
closefile(file)

// Script runs continuously until "Stop" command received.
// Idle time is shown in minutes (in intervals of powers of 2).
idle_counter = 0
idle_threshold = 1
while (remote_control)
{
	wait_for_command()
	sleep(wait_interval)
	idle_counter = idle_counter + 1
	if (idle_counter * wait_interval / 60 > idle_threshold) {
	    result(DateStamp() + ": Ready. Waiting for more than " + idle_threshold + " minute(s)...\n")
	    Result(DateStamp() + ": Ready. Waiting for command from SBEMimage...\n" )
		idle_threshold = idle_threshold * 2
    }
}

