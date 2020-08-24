// $BACKGROUND$
//
// PLEASE NOTE: The "BACKGROUND" command above is not a comment. It is
// required for this script to work properly.
//
// ========================================================================
//   This Gatan DigitalMicrograph script is part of SBEMimage, v2020.07,
//   (c) 2018-2020 Benjamin Titze,
//   Friedrich Miescher Institute for Biomedical Research, Basel, CH.
//   SBEMimage is licensed under the terms of the MIT License.
//   See LICENSE.txt in the project root folder.
//
//   This script (SBEMimage_DMcom_GMS3.s) must be running in DM to enable
//   communication between SBEMimage and 3View. It is compatible with
//   GMS 3. The other version in this folder is made for GMS 2.
// ========================================================================
//
// INSTRUCTIONS
//
// If your SBEMimage installation is not in C:\pytools\SBEMimage, you must
// change the variable install_path in line 40 before using this script.
//
// Open this script file (SBEMimage_DMcom_GMS3.s) in DigitalMicrograph (DM)
// and click "Execute".
// The script's activity is recorded in DM's output window.
// (Show output window: Menu "Window" -> "Floating Windows" -> "Output")
// After starting this script, the text in the output window should say:
// "Ready. Waiting for command from SBEMimage..."
// Now start SBEMimage.
//
// If DM crashes or behaves eratically, restart DM and restart this script.
// If the script becomes unresponsive, for example after a DM error
// message, restart it by clicking "Execute" again.
// If DM shows a "positive overflow" error message during a cut, run the
// script "tackle_overflow_error.s" in "\SBEMimage\dm".
// If the knife moves with the wrong speed during a cut, manually run one
// full record cycle from within DM with the intended knife speed.


string install_path = "C:\\pytools\\SBEMimage\\dm\\"

string input_file
string command_file
string return_file
string acknowledge_file
string acknowledge_file_cut
string warning_file
string error_file

string command
string parameter_str

number file
number err_file
number x_position
number y_position
number z_position
number parameter1
number parameter2
number t_status
number wait_interval
number idle_counter
number idle_threshold
number start_time, start_time2
number cycle_start_time
number time_elapsed, time_elapsed2, timeElapsed, timeElapsed2
number success
number remote_control
number stroke_down
number oscillator_off
number read_ok
number create_ok
number cut_ok
number near_ok
number clear_ok
number move_ok
number DS_value
number move_duration
number move_duration_x
number move_duration_y
number motor_speed_x
number motor_speed_y
number counter
number xy_tolerance
number z_tolerance


void wait_for_command()
{
	// Check if the command file exists. If yes, read command
	// string, and up to two (optional) float parameters.
	// Then execute the command.
	// List of currently implemented commands:
	//   - Handshake; no parameters
	//   - MicrotomeStage_Cut; no parameters
	//   - MicrotomeStage_Retract; no parameters
	//   - MicrotomeStage_Clear; no parameters
	//   - MicrotomeStage_Near; no parameters
	//   - MicrotomeStage_FullCut; no parameters
	//   - MicrotomeStage_FullApproachCut; no parameters
	//   - MicrotomeStage_GetPositionX; no parameters
	//   - MicrotomeStage_GetPositionY; no parameters
	//   - MicrotomeStage_GetPositionXY; no parameters
	//   - MicrotomeStage_GetPositionZ; no parameters
	//   - MicrotomeStage_SetPositionX; parameter: target X coordinate (float)
	//   - MicrotomeStage_SetPositionY; parameter: target Y coordinate (float)
	//   - MicrotomeStage_SetPositionXY; parameters: target X and Y coordinates (float)
	//   - MicrotomeStage_SetPositionXY_Confirm; parameters: target X and Y coordinates (float)
	//   - MicrotomeStage_SetPositionZ; parameter: target Z coordinate (float)
	//   - MicrotomeStage_SetPositionZ_Confirm; parameter: target Z coordinate (float)
	//   - SetMotorSpeedXY; parameters: X and Y speeds (float)
	//   - MeasureMotorSpeedXY; no parameters
	//   - StopScript; no parameters

	if (DoesFileExist(command_file))
	{
		idle_counter = 0
		idle_threshold = 1
		// Result(DateStamp() + ": Triggered! Reading command file...\n")
		read_ok = 0
		try {
			file = OpenFileForReading(command_file)
			read_ok = 1
		}
		catch {
			result(DateStamp() + ": ERROR occurred when trying to open command file.\n")
			sleep(2)
			err_file = CreateFileForWriting(error_file)
			closefile(err_file)
		}
		try {
			if (read_ok) {
				ReadFileLine(file, command)
				ReadFileLine(file, parameter_str)
				parameter1 = val(parameter_str)
				ReadFileLine(file, parameter_str)
				parameter2 = val(parameter_str)
				closefile(file)
				result(DateStamp() + ": Command received: " + command)
			}
		}
		catch {
			result(DateStamp() + ": ERROR occurred when trying to read command file.\n")
			sleep(2)
			err_file = CreateFileForWriting(error_file)
			closefile(err_file)
		}
		// Delete err/ack/wng files if they exist
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
		// Delete command file and create new input file
		DeleteFile(command_file)
		file = CreateFileForWriting(input_file)
		closefile(file)

		// ================================================================
		if (command == "Handshake") {
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
				sleep(2)
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
			try {
				if (create_ok) {
					WriteFile(file, "OK")
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.\n")
				sleep(2)
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_Cut") {
			// Only for testing purposes. Limited error handling.
			// First: Stroke up, oscillator on
			stroke_down = 0
			oscillator_off = 0
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Now cut
			if (!MicrotomeStage_Cut(1)) {
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
				result("\n" + DateStamp() + ": ERROR cutting the sample.\n")
			}
			sleep(1)
			result("\n" + DateStamp() + ": Done.\n")
			// Return to stroke down, oscillator off
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
			start_time = GetCurrentTime()
			while ((MicrotomeStage_GetClearMotorState() != 3) && clear_ok) {
				sleep(0.1)
				time_elapsed = (GetCurrentTime() - start_time) / 10000000
				if (time_elapsed > 4) {
					clear_ok = 0
					err_file = CreateFileForWriting(error_file)
					closefile(err_file)
					result("\n" + DateStamp() + ": ERROR clearing the knife.\n")
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
			start_time = GetCurrentTime()
			while ((MicrotomeStage_GetClearMotorState() != 1) && near_ok) {
				sleep(0.1)
				time_elapsed = (GetCurrentTime() - start_time) / 10000000
				if (time_elapsed > 4) {
					near_ok = 0
					err_file = CreateFileForWriting(error_file)
					closefile(err_file)
					result("\n" + DateStamp() + ": ERROR nearing the knife.\n")
				}
			}
			if (near_ok) {
				// Create acknowledge file
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result("\n" + DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_FullCut") {
			// Run a full cutting cycle with error handling.
			// This function is called during a stack acquisition.
			// The duration of one cycle is ~15 s for a cut speed of 0.2 s
			// and a retract speed of 0.6 s. This may vary depending on the
			// 3View setup and the speeds as set in DM.
			result("\n" + DateStamp() + ": ========================================================\n")
			result(DateStamp() + ": Full cut cycle in progress.\n")
			cycle_start_time = GetCurrentTime()
			cut_ok = 1
			// Move knife to "Near" position
			MicrotomeStage_Near()
			start_time = GetCurrentTime()
			while ((MicrotomeStage_GetClearMotorState() != 1) && cut_ok) {
				sleep(0.1)
				time_elapsed = (GetCurrentTime() - start_time) / 10000000
				if (time_elapsed > 4) {
					cut_ok = 0
					result(DateStamp() + ": ERROR nearing the knife.\n")
				}
			}
			// Stroke up, oscillator on
			stroke_down = 0
			oscillator_off = 0
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Cut
			if (!MicrotomeStage_Cut(1)) {
				cut_ok = 0
				result(DateStamp() + ": ERROR cutting the sample.\n")
			}
			// Stroke down, oscillator off
			stroke_down = 1
			oscillator_off = 1
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			// Retract knife
			if (!MicrotomeStage_Retract(1)) {
				cut_ok = 0
				result(DateStamp() + ": ERROR retracting the knife.\n")
			}
			// Clear knife
			clear_ok = 1
			MicrotomeStage_Clear()
			start_time = GetCurrentTime()
			while (MicrotomeStage_GetClearMotorState() != 3 && clear_ok) {
				sleep(0.1)
				time_elapsed = (GetCurrentTime() - start_time) / 10000000
				if (time_elapsed > 4) {
					clear_ok = 0
					result(DateStamp() + ": WARNING: First attempt to clear the knife failed.\n")
				}
			}
			if (!(clear_ok)) {
				// Second clear attempt: Wait, near again, then try to clear again
				result(DateStamp() + ": Second clear attempt...\n")
				sleep(2)
				MicrotomeStage_Near()
				sleep(4)
				clear_ok = 1
				MicrotomeStage_Clear()
				start_time = GetCurrentTime()
				while (MicrotomeStage_GetClearMotorState() != 3 && clear_ok) {
					sleep(0.1)
					time_elapsed = (GetCurrentTime() - start_time) / 10000000
					if (time_elapsed > 4) {
						clear_ok = 0
						cut_ok = 0
						result(DateStamp() + ": ERROR clearing the knife.\n")
					}
				}
			}
			time_elapsed = (GetCurrentTime() - cycle_start_time) / 10000000
			if (cut_ok) {
				// Create acknowledge file
				file = CreateFileForWriting(acknowledge_file_cut)
				closefile(file)
				result(DateStamp() + ": Cut cycle took " + format(time_elapsed, "%.1f") + " s.\n")
				result(DateStamp() + ": Done.\n")
			}
			else {
				// Create error file
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}

		}
		// ================================================================
		if (command == "MicrotomeStage_FullApproachCut") {
			// Run a cut cycle without near/clear, with error handling.
			// This function is called from the approach dialog.
			// The duration of one cycle is ~11 s for a cut speed of 0.2 s
			// and a retract speed of 0.6 s. This may vary depending on the
			// 3View setup and the speeds as set in DM.

			result("\n" + DateStamp() + ": ========================================================\n")
			result(DateStamp() + ": Approach cut cycle in progress.\n")
			cycle_start_time = GetCurrentTime()
			cut_ok = 1
			// Stroke up, oscillator on
			stroke_down = 0
			oscillator_off = 0
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			sleep(1)
			// Cut
			if (!MicrotomeStage_Cut(1)) {
				cut_ok = 0
				result(DateStamp() + ": ERROR cutting the sample.\n")
			}
			// Stroke down, oscillator off
			stroke_down = 1
			oscillator_off = 1
			DS_value = 64 + 32 + 16 + 8 + 4 + 2*oscillator_off + stroke_down
			DSSetDigitalOutput(DS_value)
			// Retract knife
			if (!MicrotomeStage_Retract(1)) {
				cut_ok = 0
				result(DateStamp() + ": ERROR retracting the knife.\n")
			}
			time_elapsed = (GetCurrentTime() - cycle_start_time) / 10000000
			if (cut_ok) {
				// Create acknowledge file
				file = CreateFileForWriting(acknowledge_file_cut)
				closefile(file)
				result(DateStamp() + ": Approach cut cycle took " + format(time_elapsed, "%.1f") + " s.\n")
				result(DateStamp() + ": Done.\n")
			}
			else {
				// Create error file
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionX") {
			x_position = EMGetStageX()
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
			}
			try {
				if (create_ok) {
					WriteFile(file, format(x_position, "%.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionY") {
			y_position = EMGetStageY()
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
			}
			try {
				if (create_ok) {
					WriteFile(file, format(y_position, "%.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionXY") {
			x_position = EMGetStageX()
			y_position = EMGetStageY()
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
			}
			try {
				if (create_ok) {
					WriteFile(file, format(x_position, "%.3f") + "\n" + format(y_position, "%.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.\n")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_GetPositionZ") {
			z_position = EMGetStageZ()
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
			}
			try {
				if (create_ok) {
					WriteFile(file, format(z_position, "%.3f"))
					closefile(file)
					result("\n" + DateStamp() + ": Done.\n")
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.")
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionX\n") {
			result(DateStamp() + ": Target X: " + format(parameter1, "%.3f") + "\n")
			EMSetStageX(parameter1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionY\n") {
			result(DateStamp() + ": Target Y: " + format(parameter1, "%.3f") + "\n")
			EMSetStageY(parameter1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionXY\n") {
			// Set XY position
			result(DateStamp() + ": Target X: " + format(parameter1, "%.3f") + "\n")
			result(DateStamp() + ": Target Y: " + format(parameter2, "%.3f") + "\n")
			EMSetStageX(parameter1)
			EMSetStageY(parameter2)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionXY_Confirm\n") {
			// Set the XY position and read the XY position after the move.
			// Confirm that target coordinates have been reached.
			// If not, try again. If the second attempt fails, write last
			// known coordinates to return file and create error file.
			// This function is called during stack acquisitions.
			move_ok = 1
			// result(DateStamp() + ": Target X: " + parameter1 + "\n")
			// result(DateStamp() + ": Target Y: " + parameter2 + "\n")
			// Get current coordinates
			x_position = EMGetStageX()
			y_position = EMGetStageY()
			// Calculate how long the intended move will take
			move_duration_x = abs(x_position - parameter1) / motor_speed_x
			move_duration_y = abs(y_position - parameter2) / motor_speed_y
			if (move_duration_x > move_duration_y) {
				move_duration = move_duration_x
			}
			else {
				move_duration = move_duration_y
			}
			// Motors will move simultaneously
			EMSetStageX(parameter1)
			EMSetStageY(parameter2)
			// Wait until target position reached
			result(DateStamp() + ": XY stage move in progress (expected duration: " + format(move_duration, "%.2f") + " s)\n")
			sleep(move_duration + 0.1)
			// Read new coordinates
			x_position = EMGetStageX()
			y_position = EMGetStageY()
			// Check if the current position does NOT match the target
			// position within the specified tolerance
			if ((abs(x_position - parameter1) > xy_tolerance) || (abs(y_position - parameter2) > xy_tolerance)) {
				// Create warning file and try again after 1.5 seconds
				file = CreateFileForWriting(warning_file)
				closefile(file)
				result(DateStamp() + ": WARNING - XY target coordinates not reached within the expected time.\n")
				sleep(1.5)
				// Read current stage coordinates and check again
				x_position = EMGetStageX()
				y_position = EMGetStageY()
				if ((abs(x_position - parameter1) > xy_tolerance) || (abs(y_position - parameter2) > xy_tolerance)) {
					// Move has failed. Write current position into return file.
					move_ok = 0
					file = CreateFileForWriting(return_file)
					WriteFile(file, format(x_position, "%.3f") + "\n" + format(y_position, "%.3f"))
					closefile(file)
					result(DateStamp() + ": ERROR - XY target coordinates not reached after extra 1.5s delay.\n")
				}
			}
			if (move_ok) {
				// Create acknowledge file
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
			else {
				// Create error file
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
			}
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionZ\n") {
			result(DateStamp() + ": Target Z: " + format(parameter1, "%.3f") + "\n")
			EMSetStageZ(parameter1)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MicrotomeStage_SetPositionZ_Confirm\n") {
			// Set the Z position and read the new Z position after the move.
			// If target Z was not reached, write the last known Z coordinate
			// to return file and create error file.
			// This function is called during stack acquisitions.
			result(DateStamp() + ": Target Z: " + format(parameter1, "%.3f") + "\n")
			// Move
			EMSetStageZ(parameter1)
			// Wait for execution of move
			sleep(0.5)
			// Read the new Z position
			z_position = EMGetStageZ()
			// Check if the current position does NOT match the target
			// position within specified tolerance
			if (abs(z_position - parameter1) > z_tolerance) {
				// Create error file. Write current position into
				// return file.
				err_file = CreateFileForWriting(error_file)
				closefile(err_file)
				file = CreateFileForWriting(return_file)
				WriteFile(file, format(z_position, "%.3f"))
				closefile(file)
				result(DateStamp() + ": ERROR - Target Z not reached.\n")
				result(DateStamp() + ": (Target: " + format(parameter1, "%.3f") + "; Actual: " + z_position + ")\n")
			}
			else {
				// Create acknowledge file
				file = CreateFileForWriting(acknowledge_file)
				closefile(file)
				result(DateStamp() + ": Done.\n")
			}
		}
		// ================================================================
		if (command == "SetMotorSpeedXY\n") {
			// Set motor speeds (expected speeds as measured)
			motor_speed_x = parameter1
			motor_speed_y = parameter2
			result(DateStamp() + ": Updated motor_speed_x: " + format(motor_speed_x, "%.1f") + "\n")
			result(DateStamp() + ": Updated motor_speed_y: " + format(motor_speed_y, "%.1f") + "\n")
			// Create acknowledge file
			file = CreateFileForWriting(acknowledge_file)
			closefile(file)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "MeasureMotorSpeedXY") {
			// Move both motors to the origin position (0, 0)
			start_time = GetCurrentTime()
			EMSetStageX(0)
			EMSetStageY(0)
			while ((abs(EMGetStageX()) > 0.010) || (abs(EMGetStageY()) > 0.010)) {
				sleep(1)
				timeElapsed = (GetCurrentTime() - start_time) / 10000000
				if (timeElapsed > 30) {
					Throw ("XY motors did not reach origin.")
				}
			}
			// Measure duration of 20 x 50-micron moves of X motor
			result("\n" + DateStamp() + ": Measurement started (Motor X).\n")
			start_time = GetCurrentTime()
			for (counter=1; counter<=10; counter++) {
				EMSetStageX(50)
				start_time2 = GetCurrentTime()
				while (abs(EMGetStageX()-50) > 0.010) {
					timeElapsed2 = (GetCurrentTime() - start_time2) / 10000000
					if (timeElapsed2 > 5) {
						Throw ("Motor X did not reach target position of 50.")
					}
				}
				EMSetStageX(0)
				start_time2 = GetCurrentTime()
				while (abs(EMGetStageX()) > 0.010) {
					timeElapsed2 = (GetCurrentTime() - start_time2) / 10000000
					if (timeElapsed2 > 5) {
						Throw ("Motor X did not reach target position of 0.")
					}
				}
			}
			time_elapsed = (GetCurrentTime() - start_time) / 10000000
			result(DateStamp() + ": Measurement finished (Motor X).\n")
			parameter1 = 1000 / time_elapsed
			// Measure duration of 20 x 50-micron moves of Y motor
			result(DateStamp() + ": Measurement started (Motor Y).\n")
			start_time = GetCurrentTime()
			for (counter=1; counter<=10; counter++) {
				EMSetStageY(50)
				start_time2 = GetCurrentTime()
				while (abs(EMGetStageY() - 50) > 0.010) {
					timeElapsed2 = (GetCurrentTime() - start_time2) / 10000000
					if (timeElapsed2 > 5) {
						Throw ("Motor Y did not reach target position of 50.")
					}
				}
				EMSetStageY(0)
				start_time2 = GetCurrentTime()
				while (abs(EMGetStageY()) > 0.010) {
					timeElapsed2 = (GetCurrentTime() - start_time2) / 10000000
					if (timeElapsed2 > 5) {
						Throw ("Motor Y did not reach target position of 0.")
					}
				}
			}
			time_elapsed = (GetCurrentTime() - start_time) / 10000000
			result(DateStamp() + ": Measurement finished (Motor Y).\n")
			parameter2 = 1000 / time_elapsed
			// Write to output file
			file = CreateFileForWriting(return_file)
			WriteFile(file, format(parameter1, "%.1f") + "\n" + format(parameter2, "%.1f"))
			closefile(file)
			// Create acknowledge file
			file = CreateFileForWriting(acknowledge_file)
			closefile(file)
			result(DateStamp() + ": Done.\n")
		}
		// ================================================================
		if (command == "StopScript") {
			remote_control = 0
			result("\n" + DateStamp() + ": Script stopped.\n\n")
			create_ok = 0
			try {
				file = CreateFileForWriting(return_file)
				create_ok = 1
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to open return file.\n")
			}
			try {
				if (create_ok) {
					WriteFile(file, "END")
					closefile(file)
				}
			}
			catch {
				result("\n" + DateStamp() + ": ERROR occurred when trying to write to return file.\n")
			}
		}
		t_status = 1
	}
	else
	{
		if (t_status == 1) {
			Result(DateStamp() + ": Ready. Waiting for command from SBEMimage...\n" )
			t_status = 0
		}
	}
}


// ============================ Initialization ============================

if (!DoesFileExist(install_path + "SBEMimage_DMcom_GMS3.s")) {
	Throw("Wrong install path. Please check and update the variable 'install_path' in this script.")
}

// The following files are used for communication between SBEMimage and DM:
//   DMcom.in:   Command/parameter file. Contains a command and up to
//				 two optional parameters.
//   DMcom.cmd:  The file 'DMcom.in' is renamed to 'DMcom.cmd' to trigger
//				 its contents to be processed by DM.
//   DMcom.out:  Contains return value(s) from DM
//   DMcom.ack:  Confirms that a command has been received and processed.
//   DMcom.ac2:  Confirms that a full cut cycle has been completed.
//   DMcom.wng:  Signals a warning (a problem occurred, but could be resolved).
//   DMcom.err:  Signals that a critical error occured.

input_file = install_path + "DMcom.in"
command_file = install_path + "DMcom.cmd"
return_file = install_path + "DMcom.out"
acknowledge_file = install_path + "DMcom.ack"
acknowledge_file_cut = install_path + "DMcom.ac2"
warning_file = install_path + "DMcom.wng"
error_file = install_path + "DMcom.err"

wait_interval = 0.1
remote_control = 1

// Default motor speeds (slow), can be updated from SBEMimage
motor_speed_x = 40.0
motor_speed_y = 40.0

// Tolerances in micrometres for XY and Z motors
xy_tolerance = 0.040
z_tolerance = 0.004

// Create empty input file
file = CreateFileForWriting(input_file)
closefile(file)


// ============================== MAIN LOOP ===============================

result("\n" + DateStamp() + ": ********************************************************\n")
result(DateStamp() + ": SBEMimage DMcom script started...\n")

// Script runs continuously until "Stop" command received.
// Idle time is shown in minutes (in intervals of powers of 2).
t_status = 1
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
