#-------------------------------------------------------------------------------
# Name:        calibrate.py
# Purpose:
#
# Created:     09/09/2011
#
# Copyright (c) 2011 - 2013 NVIDIA Corporation.  All rights reserved.
#
# NVIDIA Corporation and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA Corporation is strictly prohibited.
#
# Windows:
# @test python calibrate.py -i ..\testdata\5MP-ov5650\cardhu_0_5000.nvraw -p ..\testdata\5MP-ov5650\calibrate_params.cfg -o ..\results\5MP-ov5650\cardhu_0_5000\factory.bin
# @test python calibrate.py -i ..\testdata\5MP-ov5650\cardhu_0_5000.nvraw -p ..\testdata\5MP-ov5650\calibrate_params.cfg -o ..\results\5MP-ov5650\cardhu_0_5000\factory.bin --nv --debug -a ..\testdata\afcalibration.cfg
# @test python calibrate.py -i ..\testdata\sample.raw -t ..\testdata\sample.txt -p ..\testdata\calibrate_params_headerless.cfg -o ..\results\headerless\factory.bin
# @test python calibrate.py -c 0 -i ..\results\5MP-ov5650\cardhu_0_5000\cardhu_0_5000.nvraw -p ..\testdata\5MP-ov5650\calibrate_params.cfg -o ..\results\5MP-ov5650\cardhu_0_5000\factory.bin
# @test python calibrate.py -c 0 -i ..\results\5MP-ov5650\cardhu_0_5000\cardhu_0_5000.nvraw -p ..\testdata\5MP-ov5650\calibrate_params.cfg -o ..\results\5MP-ov5650\cardhu_0_5000\factory.bin
# @test python calibrate.py -c 0 -i ..\results\capture\white.nvraw -p ..\testdata\calibrate_params_camera.cfg -o ..\results\capture\factory.bin
# @test python calibrate.py -c 0 -i ..\results\sqa\white.nvraw -p ..\testdata\calibrate_params_sqa.cfg -o ..\results\sqa\sqa.bin
# Android:
# @test adb push ..\testdata\calibrate_params_camera.cfg /data/calibrate_params.cfg
#       adb shell python /data/bin-android/calibrate.py -c 0
#
#-------------------------------------------------------------------------------
#!/usr/bin/env python

from optparse import OptionParser
from optparse import make_option
import subprocess
import os
import shutil
import os.path
import sys
import ConfigParser
import string
import traceback
import time
from time import sleep
import re

__version__ = "4.2.1"

# global variables
# TODO: Eliminate all of these (except maybe the log related ones but try to do those too)
echo_commands = False
output_log_file = None
log_handle = None

# Global Constants (keep these)
adb_executable = 'adb.exe'
rcmd_executable = 'rcmd.exe'
wot_temp_dir = 'C:\\Windows\\Temp\\'

###############################
# Subroutines
###############################

def _remove_file(file):
    """Remove a file if it exists.
    """
    if (file != None):
        if (os.path.exists(file)):
            os.remove(file)

def _execute_cmd(args, silent = False):
    """Execute the command as a subprocess.
    
       Returns the exit code of the process on success
       Exit the script on failure
    """
    if (echo_commands and not silent):
        _log_msg("executing %s" % " ".join(args))
    sys.stdout.flush()

    # For Windows we need to use the shell so the path is searched (Python/Windows bug)
    # For Android, using the shell complicates things
    p = subprocess.Popen(args, shell=sys.platform.startswith('win'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (std_out_str, std_err_str) = p.communicate()

    returncode = p.returncode

    clean_std_out_str = std_out_str.translate(None,'\r')
    clean_std_err_str = std_err_str.translate(None,'\r')

    # Due to a bug in adb (http://code.google.com/p/android/issues/detail?id=3254) we always
    # get a zero return code, so if using adb search for error, not found, etc.
    if (args[0] == adb_executable):
        if (returncode == 1):
            m = re.search('error: device not found',clean_std_err_str,re.MULTILINE)
            if (m != None):
                raise RuntimeError("Unable to communicate with device.\nMake sure target device is on and connected via USB to the Windows system.") # ERRORTEXT
            m = re.search('is not recognized as an internal or external command',clean_std_err_str,re.MULTILINE)
            if (m != None):
                raise RuntimeError("Unable to locate ADB.\nMake sure ADB is installed and its location is included in the PATH environment variable.") # ERRORTEXT
        elif (returncode == 0):
            for signal in ['not found', 'error', 'No such file or directory']:
                m = re.search(signal,clean_std_out_str,re.MULTILINE)
                if (m != None):
                    returncode = 1
            for signal in ['error']:
                m = re.search(signal,clean_std_err_str,re.MULTILINE)
                if (m != None):
                    returncode = 1

    if (args[0] == rcmd_executable):
        if (returncode == 1):
            m = re.search('is not recognized as an internal or external command',clean_std_err_str,re.MULTILINE)
            if (m != None):
                raise RuntimeError("Unable to locate RCmd.\nMake sure RCmd is installed and its location is included in the PATH environment variable.") # ERRORTEXT
        elif (returncode == 0):
            m = re.search('Could not connect to target machine',clean_std_out_str,re.MULTILINE)
            if (m != None):
                raise RuntimeError("Unable to communicate with device.\nMake sure target device is on, connected via network to the Windows host system, and is running RCmdListener with the proper privileges and firewall settings.") # ERRORTEXT
            for signal in ['Command was not run, error returned from target', 'Invalid parameter', 'File was not sent successfully', 'File was not pushed, error returned from target', 'File was not pulled, error returned from target']:
                m = re.search(signal,clean_std_out_str,re.MULTILINE)
                if (m != None):
                    returncode = 1

    if (not silent):
        if (clean_std_out_str != None):
            _log_msg(clean_std_out_str)
        if (clean_std_err_str != None):
            _log_msg(clean_std_err_str)

    if (returncode != 0):
        raise RuntimeError("Failure (%d) executing command: %s" % (returncode, " ".join(args))) # ERRORTEXT

    return clean_std_out_str


def load_config_file(config_filename):
    """Read the calibration config file params and store them into the dictionary.
    """

    int_parameters = [
    ['overrides.ae.MaxSearchFrameCount', 0, 100],
    ['overrides.awb.module_cal_enable', 0, 1],
    ['overrides.lensShading.module_cal_enable', 0, 1],
    ['raw.focus_pos', 0, 32767],
    ['shared.output_jpeg_flag', 0, 1],
    ['shared.output_bmp_flag', 0, 1],
    ['shared.blob_run', 0, 1],
    ['tool.final_capture', 0, 1],
    ['tool.final_capture_check_delta_ab', 0, 1]
    ]
    float_parameters = [
    ['overrides.ae.MeanAlg.TargetBrightness', 0.0, 255.0],
    ['overrides.ae.MeanAlg.ConvergeSpeed', 0.01, 1.0],
    ['overrides.ae.MaxFstopDeltaNeg', 0.01, 1.0],
    ['overrides.ae.MaxFstopDeltaPos', 0.01, 1.0]
    ]
    bool_parameters = [
    'overrides.ap15Function.lensShading',
    'overrides.ae.MeanAlg.SmartTarget'
    ]

    config_dictionary = {}
    
    config_file = open(config_filename, "r")

    while (True):
        line = config_file.readline()
        if (line == ""):
            break

        line = line.strip()

        if (line.startswith("#") or line == ""):
            continue

        # parse the key, value pair
        tmp_list = string.split(line, "=")
        if (len(tmp_list) < 2):
            raise RuntimeError("Failed to parse configuration file parameters.") # ERRORTEXT

        # strip extra while spaces
        tmp_list[0] = tmp_list[0].strip()
        tmp_list[1] = tmp_list[1].strip()

        # remove semicolon and comments at the end
        semipos = tmp_list[1].find(';')
        if ((semipos < 0) or (len(tmp_list[1]) == 0)):
            raise RuntimeError("Invalid %s parameter in configuration file." % tmp_list[0]) # ERRORTEXT

        tmp_list[1] = tmp_list[1][:semipos]
        for param_info in int_parameters:
            if (tmp_list[0] == param_info[0]):
                try:
                    value = int(tmp_list[1])
                except ValueError:
                    raise RuntimeError("Invalid %s parameter in configuration file."  % tmp_list[0]) # ERRORTEXT
                if (value < param_info[1]):
                    raise RuntimeError("Value specified for %s is too low, value must be between %d and %d." % (tmp_list[0], param_info[1], param_info[2])) # ERRORTEXT
                if (value > param_info[2]):
                    raise RuntimeError("Value specified for %s is too high, value must be between %d and %d." % (tmp_list[0], param_info[1], param_info[2])) # ERRORTEXT
        for param_info in float_parameters:
            if (tmp_list[0] == param_info[0]):
                try:
                    value = float(tmp_list[1])
                except ValueError:
                    raise RuntimeError("Invalid %s parameter in configuration file."  % tmp_list[0]) # ERRORTEXT
                if (value < param_info[1]):
                    raise RuntimeError("Value specified for %s is too low, value must be between %d and %d." % (tmp_list[0], param_info[1], param_info[2])) # ERRORTEXT
                if (value > param_info[2]):
                    raise RuntimeError("Value specified for %s is too high, value must be between %d and %d." % (tmp_list[0], param_info[1], param_info[2])) # ERRORTEXT
        for param in bool_parameters:
            if (tmp_list[0] == param):
                if ((tmp_list[1] != 'TRUE') and (tmp_list[1] != 'FALSE')):
                    raise RuntimeError("Invalid %s parameter in configuration file."  % tmp_list[0]) # ERRORTEXT

        # add the key, value pair
        config_dictionary[tmp_list[0]] = tmp_list[1]

    config_file.close()
    return config_dictionary


def  _verify_arguments(options, config_dictionary, capture_image, local_mode):
    """Verify arguments and script mode.
    """
    error = None
    if (local_mode):
        if (not options.test_mode):
            if (options.imager_id == None):
                raise UserWarning("Missing required command line argument --camera (-c).") # ERRORTEXT
    else:
        if (options.raw_image_filename == None):
            raise UserWarning("Missing required command line argument --input (-i).") # ERRORTEXT


def create_overrides_file(config_dictionary, overrides_filename):
    """Creates the overrides file in the directory specified via raw_image_dir variable.
    """

    overrides_file = open(overrides_filename, "w")
    prefix = "overrides."

    # iterate over items from the config dictionary
    for iteritem in config_dictionary.iteritems():
        # Only care about items prefixed with "overrides."
        if (iteritem[0].startswith(prefix)):
            # print "override item: %s = %s;" % (iteritem[0], iteritem[1])
            key = iteritem[0][len(prefix):]
            overrides_file.write("%s=%s" % (key, iteritem[1]))
            # write the end semicolon and new line chars
            overrides_file.write(";\n")

    overrides_file.close()


def install_remote_script(capture_script_filename):
    """Install a given remote script on the attached Android device.
    """
    
    # execute adb remount
    _execute_cmd([adb_executable, 'remount'])

    # push raw capture script to the device
    _execute_cmd([adb_executable, 'push', capture_script_filename, '/sdcard/captureraw.py'])


def install_remote_windows_script(target_addr, capture_script_filename, device_capture_script_filename):
    """Install a given remote script on the attached Windows device.
    """

    # push capture script to the device
    _execute_cmd([rcmd_executable, '-t', target_addr, '-push', capture_script_filename, device_capture_script_filename, '-noprogress'])


def capture_image_remote(capture_script_filename, local_overrides_filename, device_overrides_filename, device_raw_image_filename, device_jpeg_image_filename, imager_id, preview_size, focus_pos, raw_image_filename, jpeg_image_filename):
    """Capture image on attached device and fetch the image file.
    
       If raw_image_filename is None, only captures jpeg using normal picture capture
    """

    raw_mode = (raw_image_filename != None)

    try:
        if (device_overrides_filename != None):
            # push overrides file
            # Save any existing overrides file (if present)
            saved_overrides_filename = device_overrides_filename + "." + str(time.time())
            _execute_cmd([adb_executable, 'shell', 'if [ -f ' + device_overrides_filename + ' ]; then mv ' + device_overrides_filename + ' ' + saved_overrides_filename + "; fi"], True)
            # Put the new one in place for capture
            _execute_cmd([adb_executable, 'push', local_overrides_filename, device_overrides_filename])

        (preview_x, preview_y) = preview_size

        # capture image using nvcs via captureraw.py

        cmd = [adb_executable, 'shell', 'python', '/sdcard/captureraw.py', str(imager_id), str(preview_x), str(preview_y)]
        if (focus_pos != None):
            cmd.append("--focuspos=" + str(focus_pos))
        cmd.append(device_jpeg_image_filename)
        if (raw_mode):
            cmd.append(device_raw_image_filename)
        _execute_cmd(cmd)

        # pull the images from the device
        if (raw_mode):
            _execute_cmd([adb_executable, 'pull', device_raw_image_filename, raw_image_filename])
        if (jpeg_image_filename != None):
            _execute_cmd([adb_executable, 'pull', device_jpeg_image_filename, jpeg_image_filename])
        else:
            # delete it if we do not want it
            _execute_cmd([adb_executable, 'shell', 'rm', device_jpeg_image_filename])

    finally:
        # Even if we abort with an error, we need to restore the original overrides file and remove ours
        if (device_overrides_filename != None):
            # delete overrides file from the device
            _execute_cmd([adb_executable, 'shell', 'rm', device_overrides_filename])
            # Restore original overrides file (if present)
            _execute_cmd([adb_executable, 'shell', 'if [ -f ' + saved_overrides_filename + ' ]; then mv ' + saved_overrides_filename + ' ' + device_overrides_filename + "; fi"], True)


def capture_image_rcmd(target_addr, camera_tool_path, imager_id, raw_mode, focus_pos, device_capture_script_filename, local_overrides_filename, device_overrides_filename, device_image_filename, image_filename):
    """Capture image on attached device connected via rcmd and fetch the image file.
    """

    # capture image using nvcs via captureraw.py
    camera_name = 'back'
    if (imager_id == 1):
        camera_name = 'front'

    # Push the overrides file to temporary filename which will be renamed by the batch file after any existing one is saved
    if (local_overrides_filename == None):
        temp_overrides_filename = 'null'
    else:
        # We put the temporary override in c:\windows\temp
        # so we do not have to create a directory ahead of time
        # because we assume it is there already
        # The batch file on the device will move it to the real location
        temp_overrides_filename = wot_temp_dir + 'temp_camera_overrides.isp'
        _execute_cmd([rcmd_executable, '-t', target_addr, '-push', local_overrides_filename, temp_overrides_filename, '-noprogress'])

    capture_params = [device_overrides_filename, temp_overrides_filename, camera_tool_path]
    if (raw_mode):
        capture_params.append('raw')
    else:
        capture_params.append('jpeg')
    if (focus_pos == None):
        capture_params.append('default')
    else:
        capture_params.append(str(focus_pos))
    capture_params.append(camera_name)
    capture_params.append(device_image_filename)

    temp_stdout_filename = 'tempstdout.' + str(time.time()) + '.txt'
    temp_stderr_filename = 'tempstderr.' + str(time.time()) + '.txt'

    _execute_cmd([rcmd_executable, '-t', target_addr, '-exec', device_capture_script_filename + ' ' + ' '.join(capture_params), '-stdout', temp_stdout_filename, '-stderr', temp_stderr_filename ])

    temp_stdout = open(temp_stdout_filename, 'r')
    stdoutstr = temp_stdout.read()
    print stdoutstr
    temp_stdout.close()
    temp_stderr = open(temp_stderr_filename, 'r')
    stderrstr = temp_stderr.read()
    sys.stderr.write(stderrstr)
    temp_stderr.close()
    _remove_file(temp_stdout_filename)
    _remove_file(temp_stderr_filename)

    for signal in ['is not recognized as an internal or external command', 'The system cannot find the path specified', 'Parameter format not correct']:
        m = re.search(signal,stderrstr,re.MULTILINE)
        if (m != None):
            raise RuntimeError("Failure (1) executing remote capture script") # ERRORTEXT

    # pull the image from the device
    _execute_cmd([rcmd_executable, '-t', target_addr, '-pull', device_image_filename, image_filename, '-noprogress'])


def _restart_media_server():
    """Restart the media server process so new property settings take effect.
    """
    #_execute_cmd(['am', 'start', '-a', 'android.media.action.IMAGE_CAPTURE'])
    #_execute_cmd(['input', 'keyevent', '4'])

    task_info = _execute_cmd(['ps', 'mediaserver'])
    #task_info =  "USER     PID   PPID  VSIZE  RSS     WCHAN    PC         NAME\nmedia     107   1     36700  9232  ffffffff 400d0670 S /system/bin/mediaserver\n"
    m = re.search('^\S+\s+(\d+)\s+',task_info,re.MULTILINE)
    if ( m == None ):
        print "WARNING: mediaserver process not located to restart." # ERRORTEXT
    else:
        pid = m.group(1)
        print "mediaserver pid: %s\n" % pid
        try:
            _execute_cmd(['kill', pid])
        except RuntimeError:
            # ignore any errors trying to kill mediaserver
            print "WARNING: mediaserver process not located to restart." # ERRORTEXT
            pass

def capture_image_local(imager_id, preview_size, focus_pos, raw_capture_image_filename, jpeg_capture_image_filename):
    """Capture jpeg and raw image from local camera.

       If raw_capture_image_filename is None, only captures jpeg using normal picture capture
    """
    import nvcamera
    raw_mode = (raw_capture_image_filename != None)

    # Required hack to disable early graph
    _execute_cmd(['setprop', 'nv-camera-disable-early-graph', '1'])
    _restart_media_server()

    # Hard coded directory in nvcs
    raw_image_dir = "/sdcard/raw"
    ograph = nvcamera.Graph()
    # create the graph
    ograph.setImager(imager_id)
    (preview_x, preview_y) = preview_size
    if (preview_x != 0):
        print "preview size: %s %s\n" % (preview_x, preview_y)
        ograph.preview(preview_x, preview_y)
    else:
        print "preview size: default\n"
        ograph.preview()
    ograph.still()
    #run the graph
    ograph.run()
    ocamera = nvcamera.Camera()
    if (raw_mode):

        ocamera.setAttr(nvcamera.attr_concurrentrawdumpflag, 7)
        ocamera.setAttr(nvcamera.attr_pauseaftercapture, 1)
        ocamera.setAttr(nvcamera.attr_exposuretime, 0.025)

        # create dirctory /data/raw because drive dumps
        # raw images in this directory
        if (os.path.exists(raw_image_dir)):
            shutil.rmtree(raw_image_dir)

        os.mkdir(raw_image_dir)

    # Turn off continuous auto focus
    try:
        ocamera.setAttr(nvcamera.attr_continuousautofocus, 0)
    except nvcamera.NvCameraException, err:
        if (err.value != nvcamera.NvError_NotSupported):
            raise

    try:
        if (focus_pos != None):
            ocamera.setAttr(nvcamera.attr_focuspos, focus_pos)
    except nvcamera.NvCameraException, err:
        if (err.value != nvcamera.NvError_NotSupported):
            raise
        else:
            raise RuntimeError("raw.focus_pos present in config file but sensor does not support it.") # ERRORTEXT

    if (preview_x != 0):
        ocamera.startPreview(preview_x, preview_y)
    else:
        ocamera.startPreview()

    if (not raw_mode):
        ocamera.waitForEvent(12000, nvcamera.CamConst_FIRST_PREVIEW_FRAME)

    ocamera.halfpress(5000)
    ocamera.waitForEvent(12000, nvcamera.CamConst_ALGS)

    ocamera.still(jpeg_capture_image_filename)
    ocamera.waitForEvent(12000, nvcamera.CamConst_CAP_READY, nvcamera.CamConst_CAP_FILE_READY)

    if (raw_mode):

        # get the list of raw files in /data/raw directory
        raw_files = os.listdir(raw_image_dir)

        # rename the file (actually moves it)
        os.rename(os.path.join(raw_image_dir, raw_files[0]), raw_capture_image_filename)

        shutil.rmtree(raw_image_dir)

    ocamera.hp_release()
    ocamera.stopPreview()
    ocamera.waitForEvent(12000, nvcamera.CamConst_PREVIEW_EOS)

    # stop and close the graph
    ograph.stop()
    ograph.close()

    # Reverse required hack to disable early graph
    _execute_cmd(['setprop', 'nv-camera-disable-early-graph', '0'])
    _restart_media_server()


###############################
# Logging Subroutines
###############################

def _open_log():
    global log_handle, output_log_file

    log_handle = open(output_log_file, "w")

def _get_output_log_filename(output_dir, log_base_name, log_suffix, is_failure):
    # change the name of the logfile
    if (is_failure):
        suffix = "_fail"
    else:
        suffix = "_success"
    dest_log_file = os.path.join(output_dir, log_base_name + suffix + log_suffix + ".txt")
    return dest_log_file

def _close_log():
    log_handle.close()

def _log_msg(msg):
    global log_handle

    print msg
    log_handle.write(msg + "\n")

def _report_success(output_dir, log_base_name, log_suffix):
    global output_log_file

    _log_msg(".d88888b.  888    d8P")
    _log_msg("d88P\" \"Y88b 888   d8P")
    _log_msg("888     888 888  d8P")
    _log_msg("888     888 888d88K")
    _log_msg("888     888 8888888b")
    _log_msg("888     888 888  Y88b")
    _log_msg("Y88b. .d88P 888   Y88b")
    _log_msg("\"Y88888P\"  888    Y88b")
    _close_log()

    dest_log_file = _get_output_log_filename(output_dir, log_base_name, log_suffix, 0)
    _remove_file(dest_log_file)
    os.rename(output_log_file, dest_log_file)


def _report_failure(output_dir, log_base_name, log_suffix):
    global output_log_file

    _log_msg("8888888888     d8888 8888888 888      8888888888 8888888b.")
    _log_msg("888           d88888   888   888      888        888  \"Y88b")
    _log_msg("888          d88P888   888   888      888        888    888")
    _log_msg("8888888     d88P 888   888   888      8888888    888    888")
    _log_msg("888        d88P  888   888   888      888        888    888")
    _log_msg("888       d88P   888   888   888      888        888    888")
    _log_msg("888      d8888888888   888   888      888        888  .d88P")
    _log_msg("888     d88P     888 8888888 88888888 8888888888 8888888P\"")
    _close_log()

    dest_log_file = _get_output_log_filename(output_dir, log_base_name, log_suffix, 1)
    _remove_file(dest_log_file)
    os.rename(output_log_file, dest_log_file)


###############################
# Main
###############################

def main():
    """Main function to execute binaries in the calibration process
    """

    # define global variables
    global echo_commands
    global output_log_file
    
    return_status = 0

    try:

        start_top = time.clock()

        #######################
        # parse arguments
        #######################

        local_mode = not sys.platform.startswith('win')

        usage = ("Usage: %prog -c <IMAGER_ID>" if local_mode else 
            "Usage: %prog [ -c <IMAGER_ID> ] -i <raw image> [ -t <headerless text file> ] -p <config file> [ -o <factory binary> ]")

        file_options = [
                make_option('-i', '--input', dest='raw_image_filename',
                        help = 'name of a raw image file'),
                make_option('-t', '--raw-text', dest = 'raw_text_filename',
                        help = 'name of the headerless raw layout description text file'),
                make_option('-p', '--params', dest='config_filename',
                        help = 'name of the configuration (parameters) file'),
                make_option('-o', '--output', dest='blob_filename',
                        help = 'name of the binary factory calibration output file'),
                make_option('-r', '--remote', dest='remote_host',
                        help = 'select remote machine (IP address or hostname)'),
            ] if (not local_mode) else [ ]

        standard_options = [
                make_option('-c', '--camera', dest='imager_id', type="int", metavar="IMAGER_ID",
                        help = 'select camera (sensor), 0 for rear facing, 1 for front facing'),
                make_option('-x', '--xtest', action='store_true', default=False,
                        dest='xtest',
                        help = 'generate calibration data that causes obvious color distortions for sanity checking'),
                make_option('-w', '--nopreview', action='store_false', default=True, dest='preview', 
                        help = 'disable preview of input image and verify image'),
                make_option('-a', '--autofocus', dest='af_filename',
                        help = 'name of an optional auto focus calibration input file'),
                make_option('--version', action='store_true', default=False,
                        dest = 'version',
                        help = 'print version string'),
                make_option('-h', '-?', '--help', action='store_true', default=False,
                        dest = 'help',
                        help = 'print this help message')
            ]

        advanced_options = [
                make_option('--nv', action='store_true', default=False, dest='advanced', help = 'enable advanced options'),
                make_option('-d', '--debug', action="store_true", default=False, 
                        dest='debug',
                        help = 'save intermediate files and provide additional diagnostic information'),
                make_option('--time', action='store_true', default=False,
                        dest = 'log_time',
                        help = 'time operations'),
                make_option('--test', action='store_true', default=False,
                        dest = 'test_mode',
                        help = 'use test mode (used by regression tests)')
            ]

        parser = OptionParser(usage, option_list=standard_options + file_options + advanced_options, add_help_option=False)

        # Make a standard options for error checking if --nv is not specified
        standard_parser = OptionParser(usage, option_list=standard_options + file_options, add_help_option=False)

        # parse the command line arguments
        (options, args) = parser.parse_args()

        # parse the standard command line arguments if --nv not present
        if (not options.advanced):
            (test_options, test_args) = standard_parser.parse_args()



        #############################
        # check and process arguments
        #############################

        if (options.version):
            print "calibrate script version %s" % __version__
            raise SystemExit()

        if (options.help):
            if (options.advanced):
                parser.print_help()
            else:
                standard_parser.print_help()
            raise SystemExit()

        capture_image = (options.imager_id != None)

        # set name suffix based on imager_id
        camera_suffix = ''
        if (capture_image):
            if (options.imager_id == 0):
                camera_suffix = ''
            elif (options.imager_id == 1):
                camera_suffix = '_front'
            else:
                raise UserWarning("Command line argument --camera (-c) must be 0 or 1.") # ERRORTEXT

        config_filename = None

        # Determine base name and input raw image filename
        if (local_mode):
            data_dir = '/sdcard'
            config_filename = os.path.join(data_dir, 'calibrate_params' + camera_suffix + '.cfg')
        else:
            config_filename = options.config_filename

        # parse and store calibration configuration file
        if (config_filename == None):
            raise UserWarning("Argument --params (-p) must be specified.") # ERRORTEXT
        config_dictionary = load_config_file(config_filename)

        _verify_arguments(options, config_dictionary, capture_image, local_mode)

        # Remote host can come from tools.remote_host or -r/--remote on the command line
        remote_host = None
        if (not local_mode):
            remote_host = options.remote_host
            if (remote_host == None):
                try:
                    remote_host = config_dictionary["tool.remote_host"]
                except KeyError:
                    pass

        # If we have a remote_host use rcmd_mode (WoT)
        rcmd_mode = (remote_host != None)
        
        # Check for prompting flag
        if (remote_host == "0.0.0.0"):
            # Prompt user for IP address
            remote_host = raw_input("Enter Windows RT Tegra device (target) IP address: ")

        # Determine base name and input raw image filename
        if (local_mode):
            raw_base_name = 'white' + camera_suffix
            raw_text_filename = None
            base_name = 'white' + camera_suffix
            raw_image_filename = os.path.join(data_dir, raw_base_name + '.nvraw')
            blob_filename = os.path.join(data_dir, "factory" + camera_suffix + ".bin")
            log_base_name = "calibrate"
            log_suffix =  camera_suffix
        else:
            raw_image_filename = options.raw_image_filename
            raw_text_filename = options.raw_text_filename
            (raw_base_name, raw_image_extension) = os.path.splitext(os.path.basename(raw_image_filename))
            if ((raw_image_extension == "nvraw") and (raw_text_filename != None)):
                raise UserWarning("Raw text file cannot be specified with an nvraw format input file (.nvraw), only a headerless raw file (.raw).") # ERRORTEXT
            blob_filename = (options.blob_filename if (options.blob_filename != None) 
                else os.path.join(os.path.dirname(raw_image_filename), raw_base_name + ".bin"))
            (base_name, blob_extension) = os.path.splitext(os.path.basename(blob_filename))
            log_base_name = base_name + "_calibrate"
            log_suffix =  ""

        output_dir = os.path.dirname(blob_filename)

        # open the log file
        output_log_file =  os.path.join(output_dir, "calibration.txt")
        _open_log()

        # Log file open at this point, so we can rename log at the end
        try:

            if (capture_image):
                if (options.imager_id == 0):
                    _log_msg("Selected rear camera.")
                elif (options.imager_id == 1):
                    _log_msg("Selected front camera.")

            # Determine path to binaries and binary extension
            if (sys.platform.startswith('win')):
                import inspect
                bin_path_name = os.path.join(os.path.dirname(sys.executable), 'bin')
                if (os.path.basename(sys.executable).lower().startswith("python")):
                    # Not using py2exe version, get script path instead
                    try:
                        bin_path_name = os.path.dirname(os.path.abspath(__file__))
                    except:
                        bin_path_name = os.path.dirname(inspect.getsourcefile(main))
                else:
                    # See if executables are really down a level
                    if (not os.path.exists(bin_path_name)):
                        bin_path_name = os.path.dirname(sys.executable)
                exe_extension = '.exe'
            else:
                #bin_path_name =  os.path.join(output_dir, "bin-android")
                bin_path_name = "/system/etc/camera/data/bin-android"
                exe_extension = ''

            if (options.debug):
                echo_commands = True
                
            try:
                focus_pos = int(config_dictionary["raw.focus_pos"])
            except KeyError:
                focus_pos = None

            try:
                convert_input_image = (int(config_dictionary["proc.translate_input_flag"]) == 1)
            except KeyError:
                # Default for convert input image is true
                convert_input_image = True

            try:
                output_jpeg_format = (int(config_dictionary["shared.output_jpeg_flag"]) == 1)
            except KeyError:
                # Default for JPEG is true
                output_jpeg_format = True

            try:
                output_bmp_format = (int(config_dictionary["shared.output_bmp_flag"]) == 1)
            except KeyError:
                # Default for BMP is false
                output_bmp_format = False

            jpeg_image_filename = os.path.join(output_dir, raw_base_name + ".jpg")
            bmp_image_filename = os.path.join(output_dir, raw_base_name + ".bmp")

            lsc_exe_name = os.path.join(bin_path_name, "lsc" + exe_extension)
            applylsc_exe_name = os.path.join(bin_path_name, "applylsc" + exe_extension)

            translated_image_filename  = os.path.join(output_dir, raw_base_name + '.nvraw')
            calibration_filename = os.path.join(output_dir, base_name + '_lsc.cfg')
            alsc_out_filename = os.path.join(output_dir, base_name + '_alsc.nvraw')
            alsc_jpeg_out_filename  = os.path.join(output_dir, base_name + '_alsc.jpg')
            alsc_bmp_out_filename = os.path.join(output_dir, base_name + '_alsc.bmp')
            stats_out_filename = os.path.join(output_dir, base_name + '_stats.csv')

            # Always do apply lsc output
            output_flat_image = True

            # Delete the local output binary file if it already exists
            if (os.path.exists(blob_filename)):
                _remove_file(blob_filename)


            ###############################
            # compute correction parameters
            # and construct binary blob
            ###############################

            # check if the image file name exists
            if (os.path.exists("/data/logs/raw_with_header.raw") != True):
                raise RuntimeError("Input raw image file %s not found." % raw_image_filename) # ERRORTEXT

            start = time.clock()

            try:
                generate_blob = (int(config_dictionary["shared.blob_run"]) == 1)
            except KeyError:
                generate_blob = True

            # run the surface generator
            cmd = []
            cmd.append(lsc_exe_name)
            #cmd.extend(['-i', raw_image_filename])
            cmd.extend(['-i', "/data/logs/raw_with_header.raw"])
            if (raw_text_filename != None):
                cmd.extend(['-r', raw_text_filename])
                cmd.extend(['-z', translated_image_filename])
            if (convert_input_image):
                if (output_jpeg_format):
                    cmd.extend(['-u', jpeg_image_filename])
                if (output_bmp_format):
                    cmd.extend(['-w', bmp_image_filename])
            cmd.extend(['-c', config_filename])
            cmd.extend(['-l', calibration_filename])
            if (output_flat_image):
                cmd.extend(['-f', alsc_out_filename])
                if (output_jpeg_format):
                    cmd.extend(['-j', alsc_jpeg_out_filename])
                if (output_bmp_format):
                    cmd.extend(['-m', alsc_bmp_out_filename])

            if (generate_blob):
                # have lsc generate the blob
                cmd.extend(['-b', blob_filename])
                if (options.af_filename != None):
                    cmd.extend(['-a', options.af_filename])

            if (options.test_mode):
                cmd.extend(['-t', stats_out_filename])
                cmd.extend(['--nv'])
            if (options.xtest):
                cmd.extend(['-x'])

            _execute_cmd(cmd)

            end = time.clock()
            if (options.log_time):
                _log_msg(">>>> time = %.3gs" % (end - start))
            start = time.clock()


            ###############################
            # install binary blob
            ###############################

            # Compute destination filename for the blob
            try:
                blob_device_filename = config_dictionary["shared.blob_full_path"]
            except KeyError:
                # Default if not present in config file
                blob_device_filename = "/sdcard/factory" + camera_suffix + ".bin"

            # Move binary blob to final destination if not test mode 
            # and if we captured an image (so we are on or connected to the device)
            if ((not options.test_mode) and capture_image):
                if (local_mode):
                    # move the blob to required location
                    shutil.move(blob_filename, blob_device_filename)
                    # Need to delete driver's cache
                    _execute_cmd(['sh', '-c', 'for i in /sdcard/nvcam/*.bin; do if [ -f $i ]; then rm $i; fi; done'])
                elif (rcmd_mode):
                    # Make sure shared.blob_full_path is valid for this OS
                    if ( blob_device_filename.find('/') >= 0 ):
                        raise RuntimeError("Configuration file parameter shared.blob_full_path is set to an invalid path for Windows RT.") # ERRORTEXT
                    # copy the blob file to device
                    _execute_cmd([rcmd_executable, '-t', remote_host, '-push', blob_filename, blob_device_filename, '-noprogress'])
                else:
                    # copy the blob file to device
                    _execute_cmd([adb_executable, 'push', blob_filename, blob_device_filename])
                    # Need to delete driver's cache
                    _execute_cmd([adb_executable, 'shell', 'for i in /sdcard/nvcam/*.bin; do if [ -f $i ]; then rm $i; fi; done'])

                # See if a final capture is to be taken to verify calibration data
                try:
                    verify_capture = (int(config_dictionary["tool.final_capture"]) == 1)
                except KeyError:
                    verify_capture = False

                if (verify_capture):
                    verify_jpeg_image_filename = os.path.join(output_dir, base_name + '_check.jpg')
                    if (local_mode):
                        # capture the image
                        capture_image_local(options.imager_id, preview_size, focus_pos, None, verify_jpeg_image_filename)
                        # Preview captured jpeg image
                        if (options.preview):
                            _execute_cmd(['sh', '-c', 'am start -S -n com.android.gallery3d/com.android.gallery3d.app.Gallery -a android.intent.action.VIEW -d file://'  + os.path.abspath(verify_jpeg_image_filename) + ' -t image/jpeg'])
                    elif (rcmd_mode):
                        # capture the image
                        # Sleep to make sure configuration data takes effect
                        sleep(2.0)
                        device_verify_jpeg_image_filename = wot_temp_dir + base_name + "_check.jpg"
                        capture_image_rcmd(remote_host, camera_tool_path, options.imager_id, False, focus_pos, device_capture_script_filename, None, device_overrides_filename, device_verify_jpeg_image_filename, verify_jpeg_image_filename)
                        # Preview captured jpeg image on WoT device
                        if (options.preview):
                            _execute_cmd([rcmd_executable, '-t', remote_host, '-exec', 'cmd /C start ' + device_verify_jpeg_image_filename])
                    else:
                        # capture the image
                        device_verify_jpeg_image_filename = '/sdcard/' + base_name + "_check.jpg"
                        capture_image_remote(capture_script_filename, None, None, None, device_verify_jpeg_image_filename, options.imager_id, preview_size, focus_pos, None, verify_jpeg_image_filename)
                        # Preview captured jpeg image on Android device
                        if (options.preview):
                            _execute_cmd([adb_executable, 'shell', 'am start -S -n com.android.gallery3d/com.android.gallery3d.app.Gallery -a android.intent.action.VIEW -d file://' + device_verify_jpeg_image_filename + ' -t image/jpeg'])

                    # Determine if a delta ab check should be done
                    try:
                        verify_capture_deltaab = (int(config_dictionary["tool.final_capture_check_delta_ab"]) == 1)
                    except KeyError:
                        verify_capture_deltaab = False
                    if (verify_capture_deltaab):
                        # Load up the image into applylsc and check delta ab
                        cmd = []
                        cmd.append(applylsc_exe_name)
                        cmd.extend(['-i', verify_jpeg_image_filename])
                        cmd.extend(['-c', config_filename])
                        cmd.extend(['--nv'])
                        cmd.extend(['--inputjpeg'])
                        cmd.extend(['--deltaonly'])
                        _execute_cmd(cmd)

            # remove intermediate files if we don't need to save them
            if (options.debug == False):
                # Only delete the calibration file if we generated a blob
                if (generate_blob):
                    _remove_file(calibration_filename)

            end = time.clock()
            if (options.log_time):
                _log_msg(">>>>Total time = %.3gs" % (end - start_top))

            _report_success(output_dir, log_base_name, log_suffix)
        except RuntimeError:
            # Just print the exception, not the full stack trace
            exc_type, exc_value, exc_traceback = sys.exc_info()
            _log_msg('ERROR: ' + str(exc_value))
            _report_failure(output_dir, log_base_name, log_suffix)
            return_status = 1
        except Exception, err:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            #traceback.print_exc()
            _log_msg('ERROR: ' + str(exc_value))
            _report_failure(output_dir, log_base_name, log_suffix)
            return_status = 1
    except UserWarning:
        # Just print the exception, not the full stack trace
        exc_type, exc_value, exc_traceback = sys.exc_info()
        sys.stderr.write('ERROR: ' + str(exc_value))
        return_status = 2
    except RuntimeError:
        # Just print the exception, not the full stack trace
        exc_type, exc_value, exc_traceback = sys.exc_info()
        sys.stderr.write('ERROR: ' + str(exc_value))
        return_status = 1
    except Exception, err:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        sys.stderr.write('ERROR: ' + str(exc_value))
        return_status = 1
    return return_status

if __name__ == '__main__':
    sys.exit(main())
