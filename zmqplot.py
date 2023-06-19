#!/usr/bin/env python

from pyqtgraph.Qt.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QFileDialog,
)

from pyqtgraph.Qt.QtGui import (
    QAction
)

from pyqtgraph.parametertree import (
    Parameter,
    ParameterTree,
    ParameterItem,
)

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

import time
import struct
import zmq
import argparse
import sys
import threading
import numpy
from lxml import objectify
import lxml.etree

NB_PLOTS = 2
DEVICE_IP = '10.1.28.34'
OUT_PORT = 9902
DELAY = 0.2
CHANNEL = 1

NB_CHAN = 2
SAVE = False
FORMAT = '4096h'
HEADERS = ''
FOOTER = ''
STREAM_TIME = False
STREAM_SPECT = False


class Pyqtgraph_app(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.init_args()
        self.set_window()
        self.set_signal_slot()
        self.run_app()

    def init_args(self):
        self.nb_plots = NB_PLOTS
        self.delay = DELAY
        self.save = SAVE
        self.Headers = HEADERS
        self.Footer = FOOTER
        self.stream_time = STREAM_TIME
        self.stream_spect = STREAM_SPECT

    def set_window(self):
        self.setWindowTitle('zmqplot.py')

        self.init_menubar()

        self.wid = QSplitter()
        self.setCentralWidget(self.wid)

        self.params = [
            {'name': 'Plot parameters', 'type': 'group', 'children': [
                {'name': 'Number of plots:', 'type': 'int', 'value': self.nb_plots},
                {'name': 'Refresh time:', 'type': 'float', 'value': self.delay},
                {'name': 'Time stream:', 'type': 'bool', 'value': self.stream_time},
                {'name': 'Spectrum stream:', 'type': 'bool', 'value': self.stream_spect},
                {'name': 'Start', 'type': 'action', 'enabled': True},
                {'name': 'Stop', 'type': 'action', 'enabled': False},
            ]},
            {'name': 'Data log options', 'type': 'group', 'children': [
                {'name': 'Save', 'type': 'bool', 'value': self.save},
                {'name': 'Header:', 'type': 'str', 'value': self.Headers},
                {'name': 'Footer:', 'type': 'str', 'value': self.Footer},
            ]},
        ]

        self.p = Parameter.create(name='params', type='group', children=self.params)
        self.tree = ParameterTree()
        self.tree.setParameters(self.p, showTop=False)
        self.plot_layout = pg.GraphicsLayoutWidget()
        self.wid.addWidget(self.tree)
        self.wid.addWidget(self.plot_layout)

        self.init_plots()


    def init_menubar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('&File')
        #edit_menu = menu_bar.addMenu('&Edit')
        #help_menu = menu_bar.addMenu('&Help')

        file_menu.addAction('Load parameters', self.loadParametersCall)
        file_menu.addAction('Save parameters', self.saveParametersCall)

    def saveParametersCall(self):

        vars = objectify.Element("item")
        vars.nb_plots = self.nb_plots
        vars.delay = self.delay
        vars.save = self.save
        vars.Headers = self.Headers
        vars.Footer = self.Footer
        vars.stream_time = self.stream_time
        vars.stream_spect = self.stream_spect

        vars.ip = str(self.ip)
        vars.port = str(self.port)
        vars.channel = str(self.channel)
        vars.nb_chan = str(self.nb_chan)
        vars.Format = str(self.Format)

        def_name = time.strftime("%Y%m%d-%H%M%S", time.gmtime(time.time())) + "-myParameters.xml"
        filename = QFileDialog.getSaveFileName(self, 'File name', def_name, "Xml files (*.xml);;All Files (*)")

        if filename[0] == '' :
            print('Parameters not saved')
        else:
            try:
                os.remove(filename[0])
            except:
                pass
            with open(filename[0], 'wb') as f:
                f.write(lxml.etree.tostring(vars, pretty_print="true", with_tail=False))
            print('Parameters saved to ' + filename[0])

    def loadParametersCall(self):
        filename = QFileDialog.getOpenFileName(self, 'File name', '', "Xml files (*.xml);;All Files (*)")
        print(filename[0])
        if filename[0] == '' :
            print('Parameters not loaded')
        else:
            with open(filename[0], 'r') as f:
                lf = objectify.fromstring(f.read())

            prev_nb_plots = self.nb_plots

            self.p.param('Plot parameters', 'Refresh time:').setValue(lf.delay)
            self.p.param('Data log options', 'Save').setValue(lf.save)
            self.p.param('Data log options', 'Header:').setValue(lf.Headers)
            self.p.param('Data log options', 'Footer:').setValue(lf.Footer)
            self.p.param('Plot parameters', 'Time stream:').setValue(lf.stream_time)
            self.p.param('Plot parameters', 'Spectrum stream:').setValue(lf.stream_spect)
            self.p.param('Plot parameters', 'Number of plots:').setValue(lf.nb_plots)

            self.ip = eval(str(lf.ip))
            self.port = eval(str(lf.port))
            self.channel = eval(str(lf.channel))
            self.nb_chan = eval(str(lf.nb_chan))
            self.Format = eval(str(lf.Format))

            self.change_plots()

            print('Parameters loaded from file ' + filename[0])

    def set_signal_slot(self):
        self.p.param('Plot parameters', 'Start').sigActivated.connect(self.start)
        self.p.param('Plot parameters', 'Stop').sigActivated.connect(self.stop)
        self.p.param('Plot parameters', 'Number of plots:').sigValueChanged.connect(self.change_plots)
        self.p.param('Data log options', 'Save').sigValueChanged.connect(self.save_changed)
        self.p.param('Plot parameters', 'Refresh time:').sigValueChanged.connect(self.tree_var_changed)
        self.p.param('Plot parameters', 'Time stream:').sigValueChanged.connect(self.tree_var_changed)
        self.p.param('Plot parameters', 'Spectrum stream:').sigValueChanged.connect(self.tree_var_changed)

    def init_variables(self):
        self.data_acq_class = [0]*self.nb_plots
        self.chan_tree = [0]*self.nb_plots
        self.sock = [0]*self.nb_plots
        self.pw = [0]*self.nb_plots
        self.curve = [0]*self.nb_plots
        self.data = [[0]*100]*self.nb_plots
        self.datas = [0]*self.nb_plots
        self.tmp = [0]*self.nb_plots
        self.ttf = [[0]*100]*self.nb_plots
        self.tmpttf = [0]*self.nb_plots
        self.ptr = [0]*self.nb_plots
        self.t0 = time.time()
        self.tf = 0
        self.ee = 0

        self.ip = [DEVICE_IP]*self.nb_plots
        self.port = [OUT_PORT]*self.nb_plots
        self.channel = [CHANNEL]*self.nb_plots
        self.nb_chan = [NB_CHAN]*self.nb_plots
        self.Format = [FORMAT]*self.nb_plots

        self.dt = float(self.delay)*1
        self.save = self.p.param('Data log options', 'Save').value()

    def change_variables(self, previous_np_plots):
        self.thread_running = True

        for i in range(previous_np_plots):
            try:
                self.sock[i].close()
            except:
                print("Sock not open")
        self.data_acq_class = [0]*self.nb_plots
        self.chan_tree = [0]*self.nb_plots
        self.sock = [0]*self.nb_plots
        self.curve = [0]*self.nb_plots
        self.data = [[0]*100]*self.nb_plots
        self.datas = [0]*self.nb_plots
        self.tmp = [0]*self.nb_plots
        self.ttf = [[0]*100]*self.nb_plots
        self.tmpttf = [0]*self.nb_plots
        self.ptr = [0]*self.nb_plots
        self.t0 = time.time()
        self.tf = 0
        self.ee = 0
        self.dt = float(self.delay)*1
        self.save = self.p.param('Data log options', 'Save').value()

        if self.nb_plots > previous_np_plots:
            self.pw.extend([0]*(self.nb_plots - previous_np_plots))
            self.ip.extend([DEVICE_IP]*(self.nb_plots - previous_np_plots))
            self.port.extend([OUT_PORT]*(self.nb_plots - previous_np_plots))
            self.channel.extend([CHANNEL]*(self.nb_plots - previous_np_plots))
            self.nb_chan.extend([NB_CHAN]*(self.nb_plots - previous_np_plots))
            self.Format.extend([FORMAT]*(self.nb_plots - previous_np_plots))
        else:
            self.pw = self.pw[0:self.nb_plots]
            self.ip = self.ip[0:self.nb_plots]
            self.port = self.port[0:self.nb_plots]
            self.channel = self.channel[0:self.nb_plots]
            self.nb_chan = self.nb_chan[0:self.nb_plots]
            self.Format = self.Format[0:self.nb_plots]

    def tree_var_changed(self):
        self.dt = float(self.p.param('Plot parameters', 'Refresh time:').value())
        for i in range(self.nb_plots):
            self.ip[i] = self.chan_tree[i].param('Channel %d' % (i+1), 'IP:').value()
            self.port[i] = self.chan_tree[i].param('Channel %d' % (i+1), 'Port:').value()
            self.Format[i] = self.chan_tree[i].param('Channel %d' % (i+1), 'Format:').value()
            self.nb_chan[i] = self.chan_tree[i].param('Channel %d' % (i+1), 'Number of channels:').value()
            self.channel[i] = self.chan_tree[i].param('Channel %d' % (i+1), 'Channels to display:').value()
            if self.data_acq_class[i] != 0:
                self.data_acq_class[i].dt = self.dt
        self.stream_time = self.p.param('Plot parameters', 'Time stream:').value()
        self.stream_spect = self.p.param('Plot parameters', 'Spectrum stream:').value()

    def save_changed(self):
        self.save = self.p.param('Data log options', 'Save').value()
        self.init_data_save()

    def init_data_save(self):
        if self.Footer != '':
            self.Footer = '_' + self.Footer
        self.filename = time.strftime("%Y%m%d-%H%M%S", time.gmtime(self.t0)) + '-RP' + self.Footer + '.dat'
        if self.save:
            self.data_file = open(self.filename, 'w')
            if self.Headers == '':
                def_headers = ''
                for i in range(self.nb_plots):
                    def_headers = def_headers + str(self.ip[i]) + ':' + str(self.port[i]) + '/' + str(self.channel[i])
                    def_headers = def_headers + '\t'
                #self.data_file.write('epoch_time\tYYYY-MM-DD\thh:mm:ss.ss\t' + def_headers + '\n')
                self.data_file.write('epoch_time\t' + def_headers + '\n')
            else:
                #self.data_file.write('epoch_time\tYYYY-MM-DD\thh:mm:ss.ss\t' + args.Headers.replace(' ','\t') + '\n')
                self.data_file.write('epoch_time\t' + args.Headers.replace(' ','\t') + '\n')

    def init_communication(self):
        context = zmq.Context()
        for i in range(self.nb_plots):
            self.sock[i] = context.socket(zmq.SUB)
            self.sock[i].setsockopt(zmq.SUBSCRIBE, "".encode('utf-8'))
            self.sock[i].setsockopt(zmq.CONFLATE,1)
            self.sock[i].connect("tcp://"+self.ip[i]+":"+str(self.port[i]))

    def init_plots(self):
        self.init_variables()
        self.init_data_save()

        self.tree.setParameters(self.p, showTop=False)
        for i in range(self.nb_plots):
            # make the tree
            channel = [
                {'name': 'Channel %d' % (i+1), 'type': 'group', 'children': [
                    {'name': 'IP:', 'type': 'str', 'value': self.ip[i]},
                    {'name': 'Port:', 'type': 'int', 'value': self.port[i]},
                    {'name': 'Format:', 'type': 'str', 'value': self.Format[i]},
                    {'name': 'Number of channels:', 'type': 'int', 'value': self.nb_chan[i]},
                    {'name': 'Channels to display:', 'type': 'int', 'value': self.channel[i]},
                ]},
            ]
            self.chan_tree[i] = Parameter.create(name='Channel %d' % (i+1), type='group', children=channel)
            self.tree.addParameters(self.chan_tree[i], showTop=False)

            # make the plot layout
            self.pw[i] = self.plot_layout.addPlot(name='Channel %d' % (i+1))
            self.plot_layout.nextRow()
            self.pw[i].setDownsampling(mode='peak')
            self.pw[i].setClipToView(True)
            self.pw[i].showGrid(True,True)
            self.curve[i] = self.pw[i].plot(pen='y')
            self.data[i] = [0]*100
            self.datas[i] = 0

            # set signal slot
            self.chan_tree[i].param('Channel %d' % (i+1), 'IP:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Port:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Format:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Number of channels:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Channels to display:').sigValueChanged.connect(self.tree_var_changed)

    def change_plots(self):
        previous_np_plots = self.nb_plots
        self.nb_plots = self.p.param('Plot parameters', 'Number of plots:').value()

        self.tree.clear()
        self.plot_layout.clear()
        self.change_variables(previous_np_plots)
        self.init_data_save()

        self.tree.setParameters(self.p, showTop=False)
        for i in range(self.nb_plots):
            # change the tree
            channel = [
                {'name': 'Channel %d' % (i+1), 'type': 'group', 'children': [
                    {'name': 'IP:', 'type': 'str', 'value': self.ip[i]},
                    {'name': 'Port:', 'type': 'int', 'value': self.port[i]},
                    {'name': 'Format:', 'type': 'str', 'value': self.Format[i]},
                    {'name': 'Number of channels:', 'type': 'int', 'value': self.nb_chan[i]},
                    {'name': 'Channels to display:', 'type': 'int', 'value': self.channel[i]},
                ]},
            ]
            self.chan_tree[i] = Parameter.create(name='Channel %d' % (i+1), type='group', children=channel)
            self.tree.addParameters(self.chan_tree[i], showTop=False)

            # change the plot layout
            self.pw[i] = self.plot_layout.addPlot(name='Channel %d' % (i+1))
            self.plot_layout.nextRow()
            self.pw[i].setDownsampling(mode='peak')
            self.pw[i].setClipToView(True)
            self.pw[i].showGrid(True,True)
            self.curve[i] = self.pw[i].plot(pen='y')
            self.data[i] = [0]*100
            self.datas[i] = 0

            # set signal slot
            self.chan_tree[i].param('Channel %d' % (i+1), 'IP:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Port:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Format:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Number of channels:').sigValueChanged.connect(self.tree_var_changed)
            self.chan_tree[i].param('Channel %d' % (i+1), 'Channels to display:').sigValueChanged.connect(self.tree_var_changed)

    def run_app(self):
        self.show()

    def closeEvent(self):
        self.stop()
        if self.save:
            self.data_file.close()
            print('filename : ' + self.filename)
            print('zmqplotqt.py IP:' + str(self.ip) + ':' + str(self.port) + ' ch' + str(self.channel) + ' dt=' + str(self.delay) + 's')
        sys.exit()

    def start(self):
        self.init_communication()
        self.p.param('Plot parameters', 'Start').setOpts(enabled=False)
        self.p.param('Plot parameters', 'Stop').setOpts(enabled=True)

        for i in range(self.nb_plots):
            self.data_acq_class[i] = data_acq_class(self.sock[i], self.dt, self.Format[i], i)
            self.data_acq_class[i].thread_running = True
            self.data_acq_class[i].update_plot.connect(self.update_plot)
            self.data_acq_class[i].update_thread()
        print("start")

    def stop(self):
        self.p.param('Plot parameters', 'Start').setOpts(enabled=True)
        self.p.param('Plot parameters', 'Stop').setOpts(enabled=False)
        for i in range(self.nb_plots):
            self.data_acq_class[i].thread_running = False
        print("stop")

    def update_plot(self, i, data):

        if self.stream_time:
            #clock=1/125e6*2**13 #remains TODO
            #lendat = len(self.data[0])
            #t_ttf = time.time() - self.t0 + np.linspace(-lendat*clock, 0 , lendat)
            data = data[int(self.channel[i])-1::self.nb_chan[i]]
            self.curve[i].setData(data, pen=pg.mkPen(1+6*i, width=1))
        elif self.stream_spect:
            data = data[int(self.channel[i])-1::self.nb_chan[i]]
            data = data*numpy.hanning(len(data))
            fft = numpy.fft.fft(data)
            freq = numpy.fft.fftfreq(len(data))
            fft = numpy.abs(fft)*2/len(data)
            self.curve[i].setData(freq, fft, pen=pg.mkPen(1+6*i, width=1))
        else:
            self.data[i][self.ptr[i]] = sum(data[self.channel[i]-1::self.nb_chan[i]])/len(data[self.channel[i]-1::self.nb_chan[i]])
            if self.save:
                self.datas[i] = sum(data[self.channel[i]-1::self.nb_chan[i]])/len(data[self.channel[i]-1::self.nb_chan[i]])
                if i == self.nb_plots-1:
                    self.datasi = str(self.datas)
                    self.datasi = self.datasi.replace('+','')
                    self.datasi = self.datasi.replace(',','\t')
                    self.datasi = self.datasi.replace('[','')
                    self.datasi = self.datasi.replace(']','')
                    self.datasi = self.datasi.replace(' ','')
                    epoch = time.time()
                    string = "%f\t%s\n" % (epoch, self.datasi)
                    self.data_file.write(string)
                    print("%f\t%s" % (epoch, self.datasi))

            self.ttf[i][self.ptr[i]] = time.time() - self.t0
            self.ptr[i] += 1
            if self.ptr[i] >= len(self.data[i]):
                self.tmpttf[i] = self.ttf[i]
                self.ttf[i] = [0] * (len(self.ttf[i]) * 2)
                self.ttf[i][:len(self.tmpttf[i])] = self.tmpttf[i]
                self.tmp[i] = self.data[i]
                self.data[i] = [0] * (len(self.data[i]) * 2)
                self.data[i][:len(self.tmp[i])] = self.tmp[i]
            self.curve[i].setData(self.ttf[i][:self.ptr[i]], self.data[i][:self.ptr[i]], pen=pg.mkPen(6+3*i, width=1))

#======================================================================================
#### Data acquisition thread

class data_acq_class(pg.GraphicsLayoutWidget):
    update_plot = QtCore.pyqtSignal(int, list)

    def __init__(self, sock, dt, Format, i):
        super(data_acq_class, self).__init__()
        self.sock = sock
        self.dt = dt
        self.Format = Format
        self.i = i
        self.init_variables()

    def init_variables(self):
        self.thread_running = True

    def update_thread(self):
        update_thread = threading.Timer(self.dt, self.update)
        update_thread.start()

    def update(self):
        update_thread = threading.Timer(self.dt, self.update)
        if self.thread_running:
            update_thread.start()
            if self.dt < 0.02:
                time.sleep(0.02)

        recv = self.sock.recv()
        data = struct.unpack(self.Format.encode('utf-8'), recv)
        self.update_plot.emit(self.i, list(data))

#======================================================================================
#### Display

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = Pyqtgraph_app()
    sys.exit(app.exec())
