# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================


from time import sleep
import serial
import threading

from microtome_control import Microtome


class Microtome_katana(Microtome):
    """
    Class for ConnectomX katana microtome. This microtome provides cutting
    functionality and controls the Z position. X and Y are controlled by the
    SEM stage. The microtome hardware is controlled via COM port commands.
    """

    def __init__(self, config, sysconfig):
        super().__init__(config, sysconfig)
        self.selected_port = sysconfig['device']['katana_com_port']
        self.clear_position = int(sysconfig['knife']['katana_clear_position'])
        self.retract_clearance = int(float(
            sysconfig['stage']['katana_retract_clearance']))
        # Realtime parameters
        self.encoder_position = None
        self.knife_position = None
        self.current_osc_freq = None
        self.current_osc_amp = None
        self.cut_completed = False 
        # Connection status:
        self.connected = False
        # Try to connect with current selected port
        self.connect()
        if self.connected:
            # wait after opening port for arduino to initialise (won't be
            # necessary in future when using extra usb-serial chip)
            sleep(1)
            # initial comm is lost when on arduino usb port. (ditto)
            self._send_command(' ')
            # clear any incoming data from the serial buffer (probably
            # not necessary here)
            self.com_port.flushInput()
            # need to delay after opening port before sending anything.
            # 0.2s fails. 0.25s seems to be always OK. Suggest >0.3s for
            # reliability.
            sleep(0.3)
            # if this software is the first to interact with the hardware
            # after power-on, then the motor parameters need to be set
            # (no harm to do anyway)
            self.initialise_motor()
            # get the initial Z position from the encoder
            self.last_known_z = self.get_stage_z()
            print('Starting Z position: ' + str(self.last_known_z) + 'µm')

    def save_to_cfg(self):
        super().save_to_cfg()
        # Save kantana-specific keys in self.syscfg
        self.syscfg['device']['katana_com_port'] = self.selected_port
        self.syscfg['knife']['katana_clear_position'] = str(
            self.clear_position)
        self.syscfg['stage']['katana_retract_clearance'] = str(
            self.retract_clearance)

    def connect(self):
        # Open COM port
        if not self.simulation_mode:
            self.com_port = serial.Serial()
            self.com_port.port = self.selected_port
            self.com_port.baudrate = 115200
            self.com_port.bytesize = 8
            self.com_port.parity = 'N'
            self.com_port.stopbits = 1
            # With no timeout, this code freezes if it doesn't get a response.
            self.com_port.timeout = 0.5
            try:
                self.com_port.open()
                self.connected = True
                # print('Connection to katana successful.')
            except Exception as e:
                print('Connection to katana failed: ' + repr(e))

    def initialise_motor(self):
         self._send_command('XM2')
         self._send_command('XY13,1')
         self._send_command('XY11,300')
         self._send_command('XY3,-3000000')
         self._send_command('XY4,3000000')
         self._send_command('XY2,0')
         self._send_command('XY6,1')
         self._send_command('XY12,0')

    def _send_command(self, cmd):
        """Send command to katana via serial port."""
        self.com_port.write((cmd + '\r').encode())
        # always need some delay after sending command.
        # suggest to keep 0.05 for now
        sleep(0.05)

    def _read_response(self):
        """Read a response from katana via the serial port."""
        return self.com_port.readline(13).decode()
        # Katana returns CR character at end of line (this is how our motor
        # controller works so it is easiest to keep it this way)

    def _wait_until_knife_stopped(self):
        print('waiting for knife to stop...')
        # initial delay to make sure we don't check before knife has
        # started moving!
        sleep(0.25)
        # knifeStatus = self._read_response()
        self.com_port.flushInput()
        while True:
            self._send_command('KKP')   # KKP queries knife movement status
            # reset it here just in case no response on next line
            knife_status = 'KKP:1'
            knife_status = self._read_response()
            knife_status = knife_status.rstrip();
            # print(" knife status: " + knifeStatus)

            # optional to show knife position so user knows it hasn't frozen!
            # _read_realtime_data is not as robust as other com port reads, and
            # there is no error check, so it should only be used for display
            # purposes. (it is very fast though, so you can use it in a loop
            # to update the GUI)
            self._read_realtime_data()
            print("Knife status: "
                  + knife_status
                  + ", \tKnife pos: "
                  + str(self.knife_position)
                  + "µm")

            if knife_status == 'KKP:0':    # If knife is not moving
                # print('Knife stationary')
                return 0
            # re-check every 0.2s. Repeated queries like this shouldnt be more
            # often than every 0.025s (risks overflowing the microtome
            # serial buffer)
            sleep(0.2)

    def _bytes_to_num(self, val_str, start, end):
        val = 0
        for i in range (start, end + 1):
            val += val_str[i] * (2**(8 * (i - start)))
        return(val)

    def _read_realtime_data(self):
        # _read_realtime_data gets the data as bytes rather than ascii. It is
        # not as robust as other com port reads, and there is no error check,
        # so it should only be used for display purposes. (it is very fast #
        # though, so you can use it in a loop to update the GUI)
        self.com_port.flushInput()
        self._send_command('KRT')
        datalength = 10
        c = self.com_port.read(datalength)
        # Can't get arduino to send negative number in binary. Temporary
        # solution is to add large number before sending and then subtract
        # it here
        self.encoder_position = self._bytes_to_num(c, 0, 3) - 10000000
        # nice to see where the knife is whilst we wait for a slow movement:
        self.knife_position = self._bytes_to_num(c, 4, 5)
        # the following gets retrieved because (when I get around to
        # implementing it) the knife will have a 'resonance mode' option. So
        # the frequency will shift to keep the knife at max amplitude
        self.current_osc_freq = self._bytes_to_num(c, 6, 7)
        # measured amplitude in nm. (Arduino scales it by 100)
        self.current_osc_amp = self._bytes_to_num(c, 8, 9) / 100
        # print(str(katana.encoderPos)+" \t"+str(katana.knifepos)
        #       +" \t"+str(katana.oscfreq)+" \t"+str(katana.oscAmp))

    def _reached_target(self):
         """Check to see if the z motor is still moving (returns 1 if target
         reached, otherwise 0 if still moving."""
         self.com_port.flushInput()
         self._send_command('XY23')
         # XY23 passes through to the motor controller.
         sleep(0.03)
         response = self._read_response()
         if response.startswith('XY23'):
             response = response.rstrip()
             response = response.replace('XY23:', '')
             status = response.split(',')
             # print(status[1])
             return int(status[1])
         else:
             return 0

    def do_full_cut(self):
        """Perform a full cut cycle. Code is run in a thread."""
        katana_cut_thread = threading.Thread(target=self.run_cut_sequence)
        self.cut_completed = False
        katana_cut_thread.start()

    def run_cut_sequence(self):
        # Move to cutting window
        # (good practice to check the knife is not moving before starting)
        self._wait_until_knife_stopped()
        print('Moving to cutting position '
              + str(self.cut_window_start) + ' ...')
        self._send_command('KMS' + str(self.knife_fast_speed))
        # send required speed. The reason I'm setting it every time before
        # moving is that I'm using two different speeds
        # (knifeFastSpeed & knifeCutSpeed)
        self._send_command('KKM' + str(self.cut_window_start))   # send required position

        # Turn oscillator on
        self._wait_until_knife_stopped()
        if self.use_oscillation:
            # turn oscillator on
            self._send_command('KO' + str(self.oscillation_frequency))
            self._send_command('KOA' + str(self.oscillation_amplitude))

        # Cut sample
        print('Cutting sample...')
        self._send_command('KMS' + str(self.knife_cut_speed))
        self._send_command('KKM' + str(self.cut_window_end))

        # Turn oscillator off
        self._wait_until_knife_stopped()
        if self.use_oscillation:
            self._send_command('KOA0')

        # Drop sample
        print('Dropping sample by ' + str(self.retract_clearance/1000) + 'µm...')
        # TODO: discuss how Z is handled:
        # drop sample before knife retract
        self.move_stage_to_z(
            self.last_known_z - self.retract_clearance / 1000, 300)

        # Retract knife
        print('Retracting knife...')
        self._send_command('KMS' + str(self.knife_fast_speed))
        self._send_command('KKM' + str(self.clear_position))

        # Raise sample to cutting plane
        self._wait_until_knife_stopped()
        print('Returning sample to cutting plane...')
        self.move_stage_to_z(self.last_known_z + self.retract_clearance / 1000, 300)
        self.cut_completed = True
        
    def check_cut_cycle_status(self):
        # Excess duration of cutting cycle in seconds
        delay = 0
        for i in range(15):
            if self.cut_completed:
                print('cut completed, returning: ', delay)
                return delay
            sleep(1)
            delay += 1
        return delay    

    def do_full_approach_cut(self):
        """Perform a full cut cycle under the assumption that knife is
           already neared."""
        pass

    def do_sweep(self, z_position):
        """Perform a sweep by cutting slightly above the surface."""
        pass

    def cut(self):
        self._send_command('KKM0')
        pass

    def retract_knife(self):
        self._send_command('KKM4000')
        pass

    def get_stage_z(self, wait_interval=0.5):
        """Get current Z position"""
        self.com_port.flushInput()
        self._send_command('KE')
        response = self._read_response()
        # response will look like 'KE:120000' (for position of 0.12mm)
        response = response.rstrip();
        response = response.replace('KE:', '')
        try:
            z = int(response) / 1000
            self.last_known_z = z
        except:
            z = None
        return z

    def get_stage_z_prev_session(self):
        return self.stage_z_prev_session

    def move_stage_to_z(self, z, speed=100, safe_mode=True):
        """Move to specified Z position, and block until it is reached."""
        print('Moving to Z=' + str(z) + 'µm...')
        # Use nanometres for katana Z position
        target_z = 1000 * z
        self._send_command('KT' + str(target_z) + ',' + str(speed))
        response = self._read_response()
        response = response.rstrip()
        while self._reached_target() != 1:
        # _reached_target() returns 1 when stage is at target position
            self._read_realtime_data()
            print('stage pos: ' + str(self.encoder_position))
            sleep(0.05)
        print('stage finished moving')
        self.last_known_z = z

    def near_knife(self):
        #self.add_to_log('ssearle - nearing knife (KKM0)') # not working. not sure how to add to log from here
        print('ssearle - nearing knife (KKM0)')
        self._send_command('KKM0')
        pass

    def clear_knife(self):
        print('ssearle - clearing knife (KKM4000)')
        self._send_command('KKM4000')
        pass

    def get_clear_position(self):
        return self.clear_position

    def set_clear_position(self, clear_position):
        self.clear_position = int(clear_position)

    def get_retract_clearance(self):
        return self.retract_clearance

    def set_retract_clearance(self, retract_clearance):
        self.retract_clearance = int(retract_clearance)

    def check_cut_cycle_status(self):
        pass

    def reset_error_state(self):
        self.error_state = 0
        self.error_info = ''

    def disconnect(self):
        if self.connected:
            self.com_port.close()
            print(f'katana: Connection closed (Port {self.com_port.port}).')