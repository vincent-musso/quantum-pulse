# Created by Gurudev Dutt <gdutt@pitt.edu> on 12/24/19
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

# this code is heavily based on Kai Zhang's code for other experiments in our group
# and is still being worked on to make it complete with the new pulse sequences introduced by Gurudev Dutt

from PyQt5 import QtCore
from Hardware.AWG520 import AWG520
from Hardware.AWG520.Sequence import Sequence,SequenceList
from Hardware.PTS3200 import PTS
from Hardware.MCL.NanoDrive import MCL_NanoDrive

import time,sys,numpy,multiprocessing
import logging


import ADwin,os

from pathlib import Path

hwdir  = Path('.')
dirPath = hwdir / 'AWG520/sequencefiles/'

modlogger = logging.getLogger('threadlogger')
modlogger.setLevel(logging.DEBUG)
# create a file handler that logs even debug messages
fh = logging.FileHandler('./logs/threadlog.log')
fh.setLevel(logging.DEBUG)
# create a console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.ERROR)
# create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
# add the handlers to the logger
modlogger.addHandler(fh)
modlogger.addHandler(ch)

_GHZ = 1000000000
_MHZ = 1000000
class UploadThread(QtCore.QThread):
    """this is the upload thread. it has following variables:
    1. seq = the sequence list of strings
    2. scan = scan parameters dictionary
    3. params = misc. params list such as count time etc
    4. awgparams = awg params dict
    5. pulseparams = pulseparams dict
    6. mwparams = mw params dict
    7. timeRes = awg clock rate in ns

    This class emits one Pyqtsignal
    1. done  - when the upload is finished
    """
    # this method only has one signal done
    done=QtCore.pyqtSignal()
    def __init__(self,parent=None,seq = None,scan = None,params = None,awgparams = None,pulseparams = None,
                 mwparams = None, timeRes = 1):
        #super().__init__(self)
        QtCore.QThread.__init__(self,parent)
        self.timeRes = timeRes
        if scan == None:
            self.scan = dict([('type', 'amplitude'), ('start', '0'), ('stepsize', '50'), ('steps', '20')])
        else:
            self.scan = scan
        if seq == None:
            self.seq = [['Green','0','1000'],['Measure','10','400']]
        else:
            self.seq = seq
        if mwparams == None:
            self.mw = {'PTS': [True, '2.870', False, '2.840', '0.001', '100', '2.940'], \
                       'SRS': [False, '2.870', False, '2.840','0.001', '100', '2.940']}
        else:
            self.mw = mwparams
        if awgparams == None:
            self.awgparams = {'awg device': 'awg520', 'time resolution': 1, \
                            'pulseshape': 'Square', 'enable IQ': False, 'iterate pulses': False, 'num pulses': 1}
        if pulseparams == None:
            self.pulseparams = {'amplitude': 0, 'pulsewidth': 20, 'SB freq': 0.00, 'IQ scale factor': 1.0,
                                'phase': 0.0, 'skew phase': 0.0}
        if params == None:
            self.parameters = [50000, 300, 1000, 10, 50, 820, 10]
                                # should make into dictionary with keys 'sample', 'count time',
                                # 'reset time', 'avg', 'threshold', 'AOM delay', 'microwave delay'

    def run(self):
        # create files
        samples = self.parameters[0]
        delay = self.parameters[-2:]

        enable_scan_pts = self.mw['PTS'][2]
        do_enable_iq = self.awgparams['enable IQ']
        npulses = self.pulseparams['num pulses']
        if enable_scan_pts:
            # we can scan frequency either using PTS or using the SB freq
            #self.scan['type'] = 'frequency'
            self.scan['type'] = 'no scan' # this tells the SeqList class to simply put one sequence as the PTS will
            # scan the frequency
        # now create teh sequences
        self.sequences = SequenceList(sequence=self.seq,delay=delay,pulseparams = self.pulseparams,scanparams = self.scan,
                                      timeres=self.timeRes)
        # write the files to the AWG520/sequencefiles directory
        self.awgfile = AWGFile(sequencelist  = self.sequences,ftype='SEQ',timeres = self.timeRes)
        self.awgfile.write_sequence(repeat = samples)
        # now upload the files
        try:
            if self.awgparamgs['device'] == 'awg520':
                self.awgcomm = AWG520()
                self.awgcomm.setup(do_enable_iq) # pass the enable IQ flag otherwise the AWG will only use one channel
                #  transfer all files to AWG
                t = time.process_time()
                for filename in os.listdir(dirPath):
                    self.awgcomm.sendfile(filename, filename)
                transfer_time = time.process_time() - t
                time.sleep(1)
                modlogger.info('time elapsed for all files to be transferred is:{0:d}'.format(transfer_time))
                self.awgcomm.cleanup()
                self.done.emit()
            else:
                raise ValueError('AWG520 is the only AWG supported')
        except ValueError:
            modlogger.error('AWG520 is only AWG supported')
            raise
        except RuntimeError as err:
            modlogger.error('Run time error'.format(err))



        
class ScanThread(QtCore.QThread):
    """this is the Scan thread. it has following variables:
        1. seq = the sequence list of strings
        2. scan = scan parameters dictionary
        3. params = misc. params list such as count time etc
        4. awgparams = awg params dict
        5. pulseparams = pulseparams dict
        6. mwparams = mw params dict
        7. timeRes = awg clock rate in ns
        8. maxcounts = observed max. counts

        This has 2 pyqtsignals
        1. data = a tuple of 2 integers which contain sig and ref counts
        2. tracking - integer with tracking counts
        """
    # declare the pyqtsignals (i) data which emits signal and ref counts , (ii) tracking which emits the tracking
    # counts
    data=QtCore.pyqtSignal(int,int)
    tracking=QtCore.pyqtSignal(int)

    def __init__(self,parent=None,scan = None,params = None,awgparams = None,pulseparams = None,mwparams = None, \
                 timeRes = 1,maxcounts=100):
        #QtCore.QThread.__init__(self,parent)
        super().__init__(parent)
        self.timeRes = timeRes
        self.maxcounts = maxcounts
        if scan == None:
            self.scan = dict([('type', 'amplitude'), ('start', '0'), ('stepsize', '50'), ('steps', '20')])
        else:
            self.scan = scan
        if mwparams == None:
            self.mw = {'PTS': [True, '2.870', False, '2.840', '0.001', '100', '2.940'], \
                       'SRS': [False, '2.870', False, '2.840', '0.001', '100', '2.940']}
        else:
            self.mw = mwparams
        if awgparams == None:
            self.awgparams = {'awg device': 'awg520', 'time resolution': 1, \
                              'pulseshape': 'Square', 'enable IQ': False}
        if pulseparams == None:
            self.pulseparams = {'amplitude': 0, 'pulsewidth': 20, 'SB freq': 0.00, 'IQ scale factor': 1.0,
                                'phase': 0.0, 'skew phase': 0.0, 'num pulses': 1}
        if params == None:
            self.parameters = [50000, 300, 1000, 10, 50, 820, 10]
            # should make into dictionary with keys 'sample', 'count time',
            # 'reset time', 'avg', 'threshold', 'AOM delay', 'microwave delay'

    def run(self):
        self.scanning=True
        self.proc_running=True

        self.p_conn,c_conn=multiprocessing.Pipe() # create parent and child connectors

        self.proc = ScanProcess(conn = c_conn)
        #self.proc.get_conn(c_conn) # give the process the child connector
        # pass the parameters to the process
        self.proc.parameters=self.parameters
        # pass the mw info
        self.proc.mw=self.mw
        # pass the scan info
        self.proc.scan=self.scan
        # pass the awg info
        self.proc.awg = self.awg
        # keep track of the maxcounts
        self.maxcounts = maxcounts
        self.proc.maxcounts=self.maxcounts
        # start the scan process
        self.proc.start()

        threshold = self.parameters[4]
        while self.scanning:
            if self.p_conn.poll(1): # check if there is data
                reply=self.p_conn.recv() # get the data
                modlogger.info('reply is ',reply)
                self.p_conn.send((threshold,self.proc_running)) # send the scan process the threshold and whether to keep running
                if reply=='Abort!':
                    self.scanning = False
                    modlogger.debug('reply is',reply)
                    break
                elif type(reply) is int: # if the reply is tracking counts, send that signal to main app
                    self.tracking.emit(reply)
                    modlogger.debug('reply emitted from tracking is {:d}'.format(reply))
                elif len(reply)==2:
                    self.data.emit(reply[0],reply[1]) # if the reply is a tuple with signal and ref,send that signal to main app
                    modlogger.debug('signal and ref emitted is {:d}'.format(reply))


class Abort(Exception):
    pass

class ScanProcess(multiprocessing.Process):
    """This is where teh scanning actually happens. It inherits nearly all the same params as the ScanThread, except for
    one more parameter: conn which is the child connector of the Pipe used to communicate to ScanThread."""
    def __init__(self,parent=None, conn = None,scan = None,params = None,awgparams = None,pulseparams = None,mwparams =
    None, timeRes = 1,maxcounts=100):
        super().__init__(parent)
        self.timeRes = timeRes
        self.maxcounts = maxcounts
        if scan == None:
            self.scan = dict([('type', 'amplitude'), ('start', '0'), ('stepsize', '50'), ('steps', '20')])
        else:
            self.scan = scan
        if mwparams == None:
            self.mw = {'PTS': [True, '2.870', False, '2.840', '0.001', '100', '2.940'], \
                       'SRS': [False, '2.870', False, '2.840', '0.001', '100', '2.940']}
        else:
            self.mw = mwparams
        if awgparams == None:
            self.awgparams = {'awg device': 'awg520', 'time resolution': 1, \
                              'pulseshape': 'Square', 'enable IQ': False}
        if pulseparams == None:
            self.pulseparams = {'amplitude': 0, 'pulsewidth': 20, 'SB freq': 0.00, 'IQ scale factor': 1.0,
                                'phase': 0.0, 'skew phase': 0.0, 'num pulses': 1}
        if params == None:
            self.parameters = [50000, 300, 1000, 10, 50, 820, 10]
            # should make into dictionary with keys 'sample', 'count time',
            # 'reset time', 'avg', 'threshold', 'AOM delay', 'microwave delay'
        self.conn = conn
        self.scanning = False
        self.initialize()


    def initialize(self):
        # for some reason the initialization was not previously carried out in an __Init__ , at first i didnt't want to change this at the moment
        # since it was working with the hardware. But will give it a try
        count_time = self.parameters[1]
        reset_time = self.parameters[2]
        samples = self.parameters[0]
        threshold = self.parameters[4]
        numavgs = self.parameters[3]
        start = self.scan['start']
        step = self.scan['stepsize']
        numsteps = self.scan['steps']
        use_pts = self.mw['PTS'][0]
        enable_scan_pts = self.mw['PTS'][2]
        current_freq = self.mw['PTS'][1]
        start_freq = self.mw['PTS'][3]
        step_freq = self.mw['PTS'][4]
        num_freq_steps = self.mw['PTS'][5]
        stop_freq = self.mw['PTS'][6]
        do_enable_iq = self.awgparams['enable IQ']
        self.adw = ADwin.ADwin()
        try:
            # boot the adwin with the bootloader
            self.adw.Boot(self.adw.ADwindir + 'ADwin11.btl')
            # Measurement protocol is configured as process 2, external triggered
            measure_proc = os.path.join(os.path.dirname(__file__), 'AdWIN',
                                        'Measure_Protocol.TB2')
            self.adw.Load_Process(measure_proc)
            # TrialCounter is configured as process 1
            count_proc = os.path.join(os.path.dirname(__file__),
                                      'ADWIN\\TrialCounter.TB1')
            self.adw.Load_Process(count_proc)
            # TODO: set the parameters in the ADWIN -- check the .BAS files
            # from what I could tell of Adbasic, these values seem to be ignored in the Measure protocol
            # double check with Elijah and maybe correct the .bas file
            self.adw.Set_Par(3, count_time)
            self.adw.Set_Par(4, reset_time)
            self.adw.Set_Par(5, samples)
            # start the Measure protocol
            self.adw.Start_Process(2)
            modlogger.info('Adwin parameter 5 is {:d}'.format(self.adw.Get_Par(5))) # seem to be printing the samples value again?
        except ADwin.ADwinError as e:
            sys.stderr.write(e.errorText)
            self.conn.send('Abort!')
            self.scanning = False

        self.awgcomm = AWG520()
        self.awgcomm.setup(do_enable_iq) # why are we setting up the AWG again? it should have been done already by Upload thread

        self.awgcomm.run()  # why are we running the sequence once? so that we can wait for the trigger?
        time.sleep(0.2)
        # initialize the PTS and output the current frequency
        if use_pts:
            self.pts = PTS()
            self.pts.write(int(current_freq * _MHZ))
        else:
            modlogger.error('No microwave synthesizer selected')

    def run(self):
        self.scanning=True
        #self.initialize() # why is initialize called in run? it would seem best to initialize hardware first
        numavgs = self.parameters[3]
        start = self.scan['start']
        step = self.scan['stepsize']
        numsteps = self.scan['steps']
        use_pts = self.mw['PTS'][0]
        enable_scan_pts = self.mw['PTS'][2]
        current_freq = self.mw['PTS'][1]
        start_freq = self.mw['PTS'][3]
        step_freq = self.mw['PTS'][4]
        num_freq_steps = self.mw['PTS'][5]
        stop_freq = self.mw['PTS'][6]
        do_enable_iq = self.awgparams['enable IQ']
        # TODO: this is still a bit ugly but because I moved the number of pulses to be scanned into pulseparams
        # TODO: I need to check if the iterate pulses is on.
        # TODO: maybe simples if in the main GUI i simply replace the scan line edits and do strict type checking in the app
        npulses = self.pulseparams['numpulses']
        if enable_scan_pts:
            # we can scan frequency either using PTS or using the SB freq
            # self.scan['type'] = 'frequency'
            self.scan['type'] = 'no scan'
            num_scan_points = num_freq_steps
        else:
            num_scan_points = numsteps
        try:
            for avg in list(range(numavgs)):
                self.awgcomm.trigger() # trigger the awg sequence
                time.sleep(0.1) # Not sure why but shorter wait time causes problem.
                for x in list(range(num_scan_points)):
                    modlogger.info('The current avg. is No.{:d}/{:d} and the the current point is {:d}/{:d}'.format(avg,numavgs,x,num_scan_points))
                    if not self.scanning:
                        raise Abort()
                    if use_pts and enable_scan_pts:
                        freq=int((start_freq+ step_freq * x)* _MHZ)
                        temp=1
                        # try to communicate with PTS and make sure it has put out the right frequency
                        while not (self.pts.write(freq)):
                            time.sleep(temp)
                            temp*=2
                            if temp>10:
                                self.pts.__init__()
                                temp=1
                    # get the signal and reference data
                    sig,ref=self.getData(x)
                    #print('id and value are',id(self.parameters[4]),self.parameters[4])
                    threshold = self.parameters[4]
                    # track the NV position if the reference counts is too low
                    while ref< threshold:
                        if not self.scanning:
                            raise Abort()
                        self.finetrack()
                        sig,ref=self.getData(x,'jump')
                        if sig==0:
                            print('sig is 0')
                            sig,ref=self.getData(x,'jump')
                        
                    self.conn.send([sig,ref])
                    modlogger.info('signal and reference data sent from ScanProc to ScanThread')
                    self.conn.poll(None)
                    self.parameters[4],self.scanning = self.conn.recv() # receive the threshold and scanning status
        except Abort:
            self.conn.send('Abort!')
            
        self.cleanup()
        

    
    def getData(self,x,*args):
        modlogger.info('entering getData with arguments {0:d},{1:}'.format(x,args))
        flag=self.adw.Get_Par(10)
        modlogger.info('Adwin Par_10 is {0:d}'.format(flag))
        
        if x==0 or args!=():
            self.awgcomm.jump(x+2) # we jump over the first 2 points in the scan?
            time.sleep(0.005)  # This delay is necessary. Otherwise neither jump nor trigger would be recognized by awg.

        self.awgcomm.trigger()
        
        if args!=():
            time.sleep(0.1)
            self.awgcomm.trigger()
            
        # wait until data updates
        while flag==self.adw.Get_Par(10):
            time.sleep(0.1)
            print(self.adw.Get_Par(20))
            
        sig=self.adw.Get_Par(1)
        ref=self.adw.Get_Par(2)
        return sig,ref
    
    def track(self):
        self.axis='z'
        position = self.nd.SingleReadN(self.axis, self.handle)
    
    def finetrack(self):
        modlogger.info('entering tracking from ScanProc')
        self.adw.Stop_Process(2)
        
        self.awgcomm.jump(1) # jumping to line 1 ?
        time.sleep(0.005)  # This delay is necessary. Otherwise neither jump nor trigger would be recognized by awg.
        self.awgcomm.trigger()

        self.nd=MCL_NanoDrive()
        self.handle=self.nd.InitHandles()['L']
        self.accuracy=0.025
        self.axis='x'
        self.scan_track()
        self.axis='y'
        self.scan_track()
        self.axis='z'
        self.scan_track(ran=0.5)
        self.nd.ReleaseAllHandles()
        
        self.adw.Start_Process(2)
        time.sleep(0.3)
        
    def go(self,command):
        position = self.nd.SingleReadN(self.axis, self.handle)
        i=0
        while abs(position-command)>self.accuracy:
            #print 'moving to',command,'from',position
            position=self.nd.MonitorN(command, self.axis, self.handle)
            time.sleep(0.1)
            i+=1
            if i==20:
                break

    def count(self):
        self.adw.Start_Process(1)
        time.sleep(1.01)
        counts=self.adw.Get_Par(1)
        self.adw.Stop_Process(1)
        return counts
    
    def scan_track(self,ran=0.25,step=0.05):
        positionList=[]
        position = self.nd.SingleReadN(self.axis, self.handle)
        counts_data=[]
        p=position-ran/2
        while p<=position+ran/2:
            positionList.append(p)
            p+=step
        for each_position in positionList:
            self.go(each_position)
            data=self.count()
            self.conn.send(data)
            self.conn.poll(None)
            r=self.conn.recv()
            self.parameters[4]=r[0]
            counts_data.append(data)
        
        self.go(positionList[counts_data.index(max(counts_data))])
        
    def cleanup(self):
        self.awgcomm.stop()
        self.awgcomm.cleanup()
        self.adw.Stop_Process(2)
        #self.amp.switch(False)
        self.pts.cleanup()
        
        
class KeepThread(QtCore.QThread):
    status=QtCore.pyqtSignal(str)
    
    def __init__(self,parent=None):
        QtCore.QThread.__init__(self,parent)
        self.running=False
    def run(self):
        self.running=True
        self.proc=KeepProcess()
        self.p_conn,c_conn=multiprocessing.Pipe()
        self.proc.get_conn(c_conn)
        self.proc.start()
        while self.running:
           # print 'keep thread running'
            if self.p_conn.poll(1):
                reply=self.p_conn.recv()
                if reply=='t':
                    self.status.emit('Tracking...')
                elif reply[0]=='c':
                    self.status.emit('Monitoring counts...'+reply[1:])
        print('keep thread stoping')
        self.p_conn.send(False)
        while self.proc.is_alive():
            print('keep proc still alive',id(self.proc.running))
            time.sleep(1)
        self.status.emit('Ready!')
        
class KeepProcess(multiprocessing.Process):
    def get_conn(self,conn):
        self.conn=conn
        self.running=False
        
    def run(self):
        print('keep process starts')
        self.running=True
        self.initialize()
        time.sleep(5)
        
        maxcount=self.count()
        self.conn.send('c'+str(maxcount))
        time.sleep(5)
        
        
        while not self.conn.poll(0.01):
            print('process did not receive anything.')
            c=self.count()
            if float(c)/maxcount<0.7:
                self.conn.send('t')
                self.track()
                maxcount=self.count()
                self.conn.send('c'+str(maxcount))
            time.sleep(5)
        
        self.cleanup()
        
    def initialize(self):
        self.nd=MCL_NanoDrive()
        self.adw=ADwin.ADwin()
        try:
            self.adw.Boot(self.adw.ADwindir + 'ADwin11.btl')
            count_proc = os.path.join(os.path.dirname(__file__),'ADWIN\\TrialCounter.TB1') # TrialCounter is configured as process 1
            self.adw.Load_Process(count_proc)
        except ADwin.ADwinError as e:
            sys.stderr.write(e.errorText)
            self.conn.send('Abort!')
            self.running=False
            
            
    def track(self):
        print('track')
        
        self.handle=self.nd.InitHandles()['L']
        self.accuracy=0.025
        self.axis='x'
        self.scan_track()
        self.axis='y'
        self.scan_track()
        self.axis='z'
        self.scan_track()
        
        
    def go(self,command):
        position = self.nd.SingleReadN(self.axis, self.handle)
        while abs(position-command)>self.accuracy:
            #print 'moving to',command,'from',position
            position=self.nd.MonitorN(command, self.axis, self.handle)
            time.sleep(0.1)

    def count(self):
        self.adw.Start_Process(1)
        time.sleep(1.01)
        counts=self.adw.Get_Par(1)
        self.adw.Stop_Process(1)
        return counts
    
    def scan_track(self,ran=0.5,step=0.05):
        positionList=[]
        position = self.nd.SingleReadN(self.axis, self.handle)
        counts_data=[]
        p=position-ran/2
        while p<=position+ran/2:
            positionList.append(p)
            p+=step
        for each_position in positionList:
            self.go(each_position)
            data=self.count()
            
            counts_data.append(data)
        
        self.go(positionList[counts_data.index(max(counts_data))])
        
    def cleanup(self):
        self.nd.ReleaseAllHandles()

