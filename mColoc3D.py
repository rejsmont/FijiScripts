import os

from javax.swing import (BoxLayout, ImageIcon, JButton, JFrame, JPanel,
        JPasswordField, JLabel, JTextArea, JTextField, JScrollPane, JList,
        DefaultListCellRenderer,
        ListSelectionModel, SwingConstants, WindowConstants)
from java.awt import Component, GridBagLayout, GridBagConstraints, Insets, Color
from java.awt.event import WindowEvent, WindowAdapter

from swingutils.models.list import DelegateListModel

from ij import IJ, ImagePlus, ImageStack, ImageListener
from ij.io import DirectoryChooser, FileSaver
from ij.gui import Roi, ShapeRoi, GenericDialog
from ij.measure import ResultsTable
from ij.plugin import Duplicator, ChannelSplitter, RGBStackMerge, ContrastEnhancer
from ij.process import StackProcessor
from loci.plugins import BF
from loci.formats import UnknownFormatException
from fiji.threshold import Auto_Threshold
from algorithms import MandersColocalization
from gadgets import DataContainer
from gadgets import ThresholdMode
from net.imglib2 import TwinCursor
from net.imglib2.img import ImagePlusAdapter
from net.imglib2.view import Views


defaultChannelA = "Channel 1"
defaultChannelB = "Channel 2"
defaultMethodA = "Mean"
defaultMethodB = "Otsu"


class MandersPlugin(ImageListener, WindowAdapter):

	def __init__(self):
		self.imp = None
		self.createMainWindow()
		self.cells = None
		self.files = []
		self.results = ResultsTable()
		ImagePlus.addImageListener(self)
		self.selectInputDir()
		self.selectOutputDir()
		self.channelA = None
		self.channelB = None
		self.methodA = None
		self.methodB = None
		self.processNextFile()

	def selectInputDir(self):
		inputDialog = DirectoryChooser("Please select a directory contaning your images")
		inputDir = inputDialog.getDirectory()
		for imageFile in os.listdir(inputDir):
			self.files.append(inputDir + imageFile)

	def selectOutputDir(self):
		outputDialog = DirectoryChooser("Please select a directory to save your results")
		self.outputDir = outputDialog.getDirectory()
		
	def closeImage(self):
		if self.imp is not None:
			self.imp.close()
			self.imp = None

	def openImage(self, imageFile):
		try:
			images = BF.openImagePlus(imageFile)
			self.imp = images[0]
		except UnknownFormatException:
			return None
		if self.imp.getNChannels() < 2:
			IJ.error("Bad image format", "Image must contain at lease 2 channels!")
			return None
		if self.channelA is None or \
			self.channelB is None or \
			self.methodA is None or \
			self.methodB is None:
			self.getOptionsDialog(self.imp)
		title = self.imp.title
		self.imp.title = title[:title.rfind('.')]
		return self.imp

	def getOptionsDialog(self, imp):
		channels = []
		methods = ["Default", "Huang", "Intermodes", "IsoData",  "Li", "MaxEntropy","Mean", "MinError(I)", "Minimum", "Moments", "Otsu", "Percentile", "RenyiEntropy", "Shanbhag" , "Triangle", "Yen"]
		for i in range(1, imp.getNChannels() + 1):
			channels.append("Channel %i" % i)
		gd = GenericDialog("Please set some options")
		gd.addChoice("Channel A", channels, defaultChannelA)
		gd.addChoice("Channel B", channels, defaultChannelB)
		gd.addChoice("Threshold method A", methods, defaultMethodA)
		gd.addChoice("Threshold method B", methods, defaultMethodB)
		gd.showDialog()
		if gd.wasCanceled():
			self.exit()
		self.channelA = channels.index(gd.getNextChoice())
		self.channelB = channels.index(gd.getNextChoice())
		self.methodA = gd.getNextChoice()
		self.methodB = gd.getNextChoice()

	def processNextFile(self):
		if self.files:
			imageFile = self.files.pop(0)
			return self.processFile(imageFile)
		else:
			return False
			
	def processFile(self, imageFile):
		imp = self.openImage(imageFile)
		if imp is not None:
			cell = Cell(imp.NSlices, 1)
			self.cells = DelegateListModel([])
			self.cells.append(cell)
			self.showMainWindow(self.cells)
			self.displayImage(imp)
			return True
		else:
			return self.processNextFile()
	
	def displayImage(self, imp):
		imp.setDisplayMode(IJ.COMPOSITE)
		enhancer = ContrastEnhancer()
		enhancer.setUseStackHistogram(True)
		splitter = ChannelSplitter()
		for c in range(1, imp.getNChannels() + 1):
			imp.c = c
			enhancer.stretchHistogram(imp, 0.35)
		imp.show()

	def getCroppedChannels(self, imp, cell):
		splitter = ChannelSplitter()
		imp.setRoi(None)
		cropRoi = cell.getCropRoi()
		if cropRoi is None:
			return None
		crop = cropRoi.getBounds()
		channels = []
		for c in range(1, imp.getNChannels() + 1):			
			slices = ImageStack(crop.width, crop.height)
			channel = splitter.getChannel(imp, c)
			for z in range(1, channel.getSize() + 1):
				zslice = channel.getProcessor(z)
				zslice.setRoi(cropRoi)
				nslice = zslice.crop()
				if cell.slices[z - 1].roi is not None:
					roi = cell.slices[z - 1].roi.clone()
					bounds = roi.getBounds()
					roi.setLocation(bounds.x - crop.x, bounds.y - crop.y)
					nslice.setColor(Color.black)
					nslice.fillOutside(roi)
					slices.addSlice(nslice)
			channels.append(ImagePlus("Channel %i" % c, slices))
		return channels

	def getThreshold(self, imp, method):
		thresholder = Auto_Threshold()
		duplicator = Duplicator()
		tmp = duplicator.run(imp)
		return thresholder.exec(tmp, method, False, False, True, False, False, True)

	def getContainer(self, impA, impB):
		imgA = ImagePlusAdapter.wrap(impA)
		imgB = ImagePlusAdapter.wrap(impB)
		return DataContainer(imgA, imgB, 1, 1, "imageA", "imageB")

	def getManders(self, imp, cell, chA, chB, methodA, methodB):
		channels = self.getCroppedChannels(imp, cell)
		if channels is None:
			return None
		manders = MandersColocalization()
		container = self.getContainer(channels[chA], channels[chB])
		img1 = container.getSourceImage1()
		img2 = container.getSourceImage2()
		mask = container.getMask()
		thr1, thrimp1 = self.getThreshold(channels[chA], methodA)
		thr2, thrimp2 = self.getThreshold(channels[chB], methodB)
		cursor = TwinCursor(img1.randomAccess(), img2.randomAccess(), Views.iterable(mask).localizingCursor())
		rtype = img1.randomAccess().get().createVariable()
		raw = manders.calculateMandersCorrelation(cursor, rtype)
		rthr1 = rtype.copy()
		rthr2 = rtype.copy()
		rthr1.set(thr1)
		rthr2.set(thr2)
		cursor.reset()
		thrd = manders.calculateMandersCorrelation(cursor, rthr1, rthr2, ThresholdMode.Above)
		return (channels, [thrimp1, thrimp2], [thr1, thr2], raw, thrd)

	def saveMultichannelImage(self, title, channels, luts):
		tmp = RGBStackMerge.mergeChannels(channels, False)
		tmp.luts = luts
		saver = FileSaver(tmp)
		saver.saveAsTiffStack(self.outputDir + title + ".tif")
		tmp.close()
		

	def createMainWindow(self):
		self.frame = JFrame('Select cells and ROIs',
			defaultCloseOperation = JFrame.DISPOSE_ON_CLOSE
		)
		self.frame.setLayout(GridBagLayout())
		self.frame.addWindowListener(self)

		self.frame.add(JLabel("Cells"),
			GridBagConstraints(0, 0, 1, 1, 0, 0,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(5, 2, 2, 0), 0, 0
		))
		
		self.cellList = JList(DelegateListModel([]),
			selectionMode = ListSelectionModel.SINGLE_SELECTION,
			cellRenderer = MyRenderer(),
			selectedIndex = 0,
			valueChanged = self.selectCell
		)
		self.frame.add(JScrollPane(self.cellList),
			GridBagConstraints(0, 1, 1, 5, .5, 1,
				GridBagConstraints.CENTER, GridBagConstraints.BOTH,
				Insets(0, 2, 2, 0), 0, 0
		))

		self.frame.add(JButton('Add cell', actionPerformed = self.addCell),
			GridBagConstraints(1, 2, 1, 2, 0, .25,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(0, 0, 0, 0), 0, 0
		))
    	
		self.frame.add(JButton('Remove cell', actionPerformed = self.removeCell),
			GridBagConstraints(1, 4, 1, 2, 0, .25,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(0, 5, 0, 5), 0, 0
		))
		
		self.frame.add(JLabel("Slices"),
			GridBagConstraints(0, 6, 1, 1, 0, 0,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(5, 2, 2, 0), 0, 0
		))
		
		self.sliceList = JList(DelegateListModel([]),
			selectionMode = ListSelectionModel.SINGLE_SELECTION,
			cellRenderer = MyRenderer(),
			selectedIndex = 0,
			valueChanged = self.selectSlice
		)
		self.frame.add(JScrollPane(self.sliceList),
			GridBagConstraints(0, 7, 1, 5, .5, 1,
				GridBagConstraints.CENTER, GridBagConstraints.BOTH,
				Insets(0, 2, 2, 0), 0, 0
		))

		self.frame.add(JButton('Update ROI', actionPerformed = self.updateSlice),
			GridBagConstraints(1, 8, 1, 2, 0, .25,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(0, 0, 0, 0), 0, 0
		))

		self.frame.add(JButton('Done', actionPerformed = self.doneSelecting),
			GridBagConstraints(1, 10, 1, 2, 0, .25,
				GridBagConstraints.CENTER, GridBagConstraints.NONE,
				Insets(0, 0, 0, 0), 0, 0
		))

	def showMainWindow(self, cells = None):
		if cells is not None:
			self.cellList.model = cells
			if cells:
				self.cellList.selectedIndex = 0
		self.frame.pack()
		self.frame.visible = True

	def hideMainWindow(self):
		self.frame.visible = False

	def closeMainWindow(self):
		self.frame.dispose()

	def addCell(self, event):
		size = len(self.cells)
		if (size > 0):
			last = self.cells[size - 1]
			n = last.n + 1
		else:
			n = 1
		self.cells.append(Cell(self.imp.NSlices, n))
		self.cellList.selectedIndex = size

	def removeCell(self, event):
		selected = self.cellList.selectedIndex
		if selected >= 0:
			self.cells.remove(self.cells[selected])
			if (selected >= 1):
				self.cellList.selectedIndex = selected - 1
			else:
				self.cellList.selectedIndex = 0

	def selectCell(self, event):
		selected = self.cellList.selectedIndex
		if selected >= 0:
			cell = self.cells[selected]
			self.sliceList.model = cell.slices
			self.sliceList.selectedIndex = 0
		else:
			self.sliceList.model = DelegateListModel([])

	def selectSlice(self, event):
		selectedCell = self.cellList.selectedIndex
		selectedSlice = self.sliceList.selectedIndex
		if selectedCell >= 0 and selectedSlice >= 0:
			cell = self.cells[selectedCell]
			image = self.imp
			if image is not None and cell is not None:
				roi = cell.slices[selectedSlice].roi
				if (image.z - 1 != selectedSlice):
					image.z = selectedSlice + 1				
				image.setRoi(roi, True)

	def updateSlice(self, event):
		selectedCell = self.cellList.selectedIndex
		selectedSlice = self.sliceList.selectedIndex
		if selectedCell >= 0  and selectedSlice >= 0:
			cell = self.cells[selectedCell]
			image = self.imp
			if image is not None and cell is not None:
				imageRoi = image.getRoi()
				if imageRoi is not None:
					index = selectedSlice + 1
					roi = ShapeRoi(imageRoi, position = index)
					cell.slices[selectedSlice].roi = roi
					if (index + 1 <= len(cell.slices)):
						image.z = index + 1
			self.cellList.repaint(self.cellList.getCellBounds(selectedCell, selectedCell))
			self.sliceList.repaint(self.sliceList.getCellBounds(selectedSlice, selectedSlice))
		
	def imageOpened(self, imp):
		pass

	def imageClosed(self, imp):
		pass

	def imageUpdated(self, imp):
		if imp is not None:
			selectedCell = self.cellList.selectedIndex
			selectedSlice = imp.z - 1
		if imp == self.imp and selectedSlice != self.sliceList.selectedIndex:
			self.sliceList.selectedIndex = selectedSlice

	def doneSelecting(self, event):
		oluts = self.imp.luts
		luts = []
		luts.append(oluts[self.channelA])
		luts.append(oluts[self.channelB])
		for cell in self.cells:
			manders = self.getManders(self.imp, cell, self.channelA, self.channelB, self.methodA, self.methodB)
			if manders is not None:
				chimps, thrimps, thrs, raw, thrd = manders
				index = self.cells.index(cell) + 1
				title = "Cell_%i-" % index + self.imp.title
				self.saveMultichannelImage(title, chimps, oluts)
				title = "Cell_%i_thrd-" % index + self.imp.title
				self.saveMultichannelImage(title, thrimps, luts)
				self.results.incrementCounter()
				row = self.results.getCounter() - 1
				self.results.setValue("Threshold 1", row, int(thrs[0]))
				self.results.setValue("Threshold 2", row, int(thrs[1]))
				self.results.setValue("M1 raw", row, float(raw.m1))
				self.results.setValue("M2 raw", row, float(raw.m2))
				self.results.setValue("M1 thrd", row, float(thrd.m1))
				self.results.setValue("M2 thrd", row, float(thrd.m2))
		self.closeImage()
		if not self.processNextFile():
			print "All done - happy analysis!"
			self.results.show("Manders collocalization results")
			self.exit()

	def windowClosing(self, e):
		print "Closing plugin - BYE!!!"
		self.exit()

	def exit(self):
		ImagePlus.removeImageListener(self)
		self.closeImage()
		self.closeMainWindow()


class Cell(object):

	def __init__(self, nslices, n):
		self.n = n
		self.slices = DelegateListModel([])
		self.initSlices(nslices)
		self.name = "Cell %i" % self.n
	
	def initSlices(self, nslices):
		for i in range(1, nslices + 1):
			aslice = Slice("Slice %i" % i)
			self.slices.append(aslice)

	def isDefined(self):
		size = len(self.slices)
		if size <= 0:
			return False
		for i in range(0, size):
			aslice = self.slices[i]
			if not aslice.isDefined():
				return False
		return True

	def getCropRoi(self):
		crop = None
		for aslice in self.slices:
			roi = aslice.roi
			if roi is not None:
				if crop is None:
					crop = roi.clone()
				else:
					crop.or(roi)
		return crop

		
class Slice(object):

	def __init__(self, name):
		self.roi = None
		self.name = name

	def isDefined(self):
		return self.roi is not None


class MyRenderer(DefaultListCellRenderer):

	def getListCellRendererComponent(self, list, value, index, isSelected, cellHasFocus):
		c = DefaultListCellRenderer.getListCellRendererComponent(
			self, list, value, index, isSelected, cellHasFocus
		)
		self.setText(value.name)
		if isSelected and not value.isDefined():
			self.setBackground(Color.red)
		if not isSelected and not value.isDefined():
			self.setForeground(Color.red)
		
		return c


colocalizer = MandersPlugin()
