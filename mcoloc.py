### Colocalization script for Alessia using new and awesome ImgLib2 functions
### and a bit more user-friendly (need to write some GUI though)
###
### Modified from colocalization macro I wrote for Maya in December 2014
###
### @author Radoslaw Kamil Ejsmont <radoslaw@ejsmont.net>
### @license Licensed under GPLv3 and CC BY 4.0

import os

from ij import IJ, ImagePlus, ImageStack
from ij.io import DirectoryChooser, OpenDialog, FileSaver
from ij.gui import WaitForUserDialog
from ij.measure import ResultsTable
from ij.plugin import ChannelSplitter, RGBStackMerge, ZProjector, ContrastEnhancer, CompositeConverter, Duplicator
from ij.plugin.frame import RoiManager
from ij.process import Blitter, ImageConverter
from fiji.threshold import Auto_Threshold
from loci.plugins import BF
from loci.formats import UnknownFormatException

from algorithms import MandersColocalization
from net.imglib2 import TwinCursor
from net.imglib2.img import ImagePlusAdapter
from net.imglib2.view import Views
from gadgets import DataContainer
from gadgets import ThresholdMode


inputDialog = DirectoryChooser("Please select a directory contaning your images")
outputDialog = DirectoryChooser("Please select a directory to save your results")
inputDir = inputDialog.getDirectory()
outputDir = outputDialog.getDirectory()

imageA = 2  # Second channel
imageB = 3  # Third channel
methods = ["Mean", "Otsu"]


def createContainer(roi, imgA, imgB):
	rect = roi.getBounds()
	ipmask = roi.getMask()
	offset = [rect.x, rect.y]
	size = [rect.width, rect.height]
	if (ipmask != None):
		ipslice = ipmask.createProcessor(imgA.getWidth(), imgA.getHeight())
		ipslice.setValue(0.0)
		ipslice.fill()
		ipslice.copyBits(ipmask, rect.x, rect.y, Blitter.COPY)
		impmask = ImagePlus("Mask", ipslice)
		ipamask = ImagePlusAdapter.wrap(impmask)
		container = DataContainer(imgA, imgB, 1, 1, "imageA", "imageB", ipamask, offset, size)
	else:
		container = DataContainer(imgA, imgB, 1, 1, "imageA", "imageB", offset, size)

	return container

def calculateThreshold(image, roi, method):
	if roi != None:
		bounds = roi.getBounds()
		stack = image.getStack()
		newstack = ImageStack(bounds.width, bounds.height)
		for i in xrange(1, stack.getSize() + 1):
  			ip = stack.getProcessor(i).duplicate()
  			ip.fillOutside(roi)
  			ip.setRoi(roi)
			c = ip.crop()
			newstack.addSlice(str(i), c)
		imp = ImagePlus("ThresholdImage", newstack)
	else:
		imp = image
	thresholder = Auto_Threshold()
	result = thresholder.exec(imp, method, False, False, True, False, False, True)

	return result

def getPreview(image):
	enhancer = ContrastEnhancer()
	projector = ZProjector()
	splitter = ChannelSplitter()
	imp1 = ImagePlus("CH1", )
	width, height, channels, slices, frames = image.getDimensions()
	chimps = []
	for ch in range(1, channels + 1):
		projector = ZProjector(ImagePlus("C%i" % ch, splitter.getChannel(image, ch)))
		projector.setMethod(ZProjector.MAX_METHOD)
		projector.doProjection()
		proj = projector.getProjection()
		enhancer.equalize(proj)
		chimps.append(proj)
		
	return RGBStackMerge.mergeChannels(chimps, False)

manders = MandersColocalization()
results = ResultsTable()
for imageFile in os.listdir(inputDir):
	print "Opening " + imageFile
	try:
		images = BF.openImagePlus(inputDir + imageFile)
		image = images[0]
	except UnknownFormatException:
		continue
	preview = getPreview(image)
	preview.show()
	rm = RoiManager()
	dialog = WaitForUserDialog("Action required", "Please select regions of interest in this image. Click OK when done.")
	dialog.show()
	rm.close()
	splitter = ChannelSplitter()
	imp1 = ImagePlus("CH1", splitter.getChannel(image, imageA))
	imp2 = ImagePlus("CH2", splitter.getChannel(image, imageB))
	title = image.getTitle()
	title = title[:title.rfind('.')]
	image.close()
	preview.close()
	ch1 = ImagePlusAdapter.wrap(imp1)
	ch2 = ImagePlusAdapter.wrap(imp2)

	for roi in rm.getRoisAsArray():
		container = createContainer(roi, ch1, ch2)
		img1 = container.getSourceImage1()
		img2 = container.getSourceImage2()
		mask = container.getMask()
		
		thr1, thrimp1 = calculateThreshold(imp1, roi, methods[0])
		thr2, thrimp2 = calculateThreshold(imp2, roi, methods[1])
		
		cursor = TwinCursor(img1.randomAccess(), img2.randomAccess(), Views.iterable(mask).localizingCursor())
		rtype = img1.randomAccess().get().createVariable()
		raw = manders.calculateMandersCorrelation(cursor, rtype)
		rthr1 = rtype.copy()
		rthr2 = rtype.copy()
		rthr1.set(thr1)
		rthr2.set(thr2)
		cursor.reset()
		thrd = manders.calculateMandersCorrelation(cursor, rthr1, rthr2, ThresholdMode.Above)
		print "Results are: %f %f %f %f" % (raw.m1, raw.m2, thrd.m1, thrd.m2)

		results.incrementCounter()
		rowno = results.getCounter() - 1
		results.setValue("Cell", rowno, int(rowno))
		results.setValue("Threshold 1", rowno, int(thr1))
		results.setValue("Threshold 2", rowno, int(thr2))
		results.setValue("M1 raw", rowno, float(raw.m1))
		results.setValue("M2 raw", rowno, float(raw.m2))
		results.setValue("M1 thrd", rowno, float(thrd.m1))
		results.setValue("M2 thrd", rowno, float(thrd.m2))
		
		thrimp = RGBStackMerge.mergeChannels([thrimp1, thrimp2], False)
		saver = FileSaver(thrimp)
		saver.saveAsTiffStack(outputDir + "Cell_%i-" % results.getCounter() + title + ".tif")
		thrimp.close()

results.show("Colocalization results")
