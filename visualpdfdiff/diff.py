#!/usr/bin/env python

# Required for zip_longest
from future import standard_library
standard_library.install_aliases()

import sys
try: from pathlib2 import Path
except ImportError: from pathlib import Path
from itertools import zip_longest

from consolemsg import step, warn, out, fail

def step(*args): pass

def tmpchanges(context):
	"""Control uncleaned temporary files"""
	current = set(Path('/tmp').glob('*'))
	tmpchanges.initial = tmpchanges.initial if hasattr(tmpchanges, 'initial') else current
	previous = tmpchanges.previous if hasattr(tmpchanges, 'previous') else set()
	added = current - previous
	removed = previous - current
	tmpchanges.previous = current
	if not added and not removed: return
	if tmpchanges.initial == current: return
	warn("{}: Temporary files left behind:\n{}", context, '\n'.join([
		"+ {}".format(tmp) for tmp in added] + [
		"- {}".format(tmp) for tmp in removed] + [
		"  {}".format(tmp) for tmp in current-tmpchanges.initial-added] + [
	]))
	

def buildDiffPdf(a, b, overlay, output, **params):
	import PyPDF2
	from io import open, BytesIO

	if overlay:
		overlayfile = BytesIO(overlay)

	step("Building diff pdf")
	def pages(reader):
		for i in range(reader.getNumPages()):
			yield reader.getPage(i)

	with \
		a.open('rb') as afile, \
		b.open('rb') as bfile, \
		output.open('wb') as outputfile \
		:
		areader = PyPDF2.PdfFileReader(afile)
		breader = PyPDF2.PdfFileReader(bfile)
		diffreader = PyPDF2.PdfFileReader(overlayfile)
		writer = PyPDF2.PdfFileWriter()
		# TODO: zip_longest instead of zip and manage Nones
		def blankLike(otherPage):
			return PyPDF2.pdf.PageObject.createBlankPage(
				width=otherPage.mediaBox.getUpperRight_x(),
				height=otherPage.mediaBox.getLowerRight_y(),
			)

		for apage, bpage, diffpage in zip_longest(pages(areader), pages(breader), pages(diffreader)):
			step(" Building page")
			missingA = not apage
			missingB = not bpage
			assert diffpage
			apage = apage or blankLike(bpage)
			bpage = bpage or blankLike(apage)
			xoffset = apage.mediaBox.getUpperRight_x()
			apage.mergeTranslatedPage(bpage, xoffset, 0, True)
			if not missingB:
				apage.mergeTranslatedPage(diffpage, 0, 0, True)
			if not missingA:
				apage.mergeTranslatedPage(diffpage, xoffset, 0, True)
			writer.addPage(apage)
		step(" Writing pdf")
		writer.write(outputfile)

def centeredText(page, text):
	"Draws a centered text in the middle of a page"
	page.alpha_channel='activate'
	page.opaque_paint('black', 'rgba(240,255,255,.4)', channel='all_channels')
	from wand.drawing import Drawing
	with Drawing() as draw:
		draw.fill_color='rgba(255,0,0,1)'
		draw.stroke_color='grey'
		draw.stroke_width = 2
		draw.font_size=40
		draw.font_weight = 700
		draw.gravity='center'
		draw.text(0,0,text)
		draw.stroke_color = 'transparent'
		draw.text(0,0,text)
		draw(page)

def highlightDifferences(diffimage):
	"""Takes a B/W image with different pixels in white
	over a black background and returns a highlight
	semitransparent overlay with the corresponding pixels
	encircled in red.
	"""
	# expand diffed dots to fill holes and having a margin
	diffimage.morphology(method='dilate',kernel='square:2')
	# invert to compute the edge arround them
	diffimage.negate()
	# find the edge, 2 points wide
	diffimage.edge(2)
	# say we wanna have effect on alpha as well
	diffimage.channel='argb'
	# needed for?
	diffimage.fill_color='red'
	# excange the white color by red
	diffimage.opaque_paint('white', 'red')
	# activate the alpha channel
	diffimage.alpha_channel='activate'
	# exchange the black color by semitransparent white
	diffimage.opaque_paint('black', 'rgba(240,255,255,.4)', channel='all_channels')

def rasterize(pdfimage):
	# pdf's just have the inked parts, so,
	# in order to simulate white paper
	# alpha channel is removed using white
	# as background color
	pdfimage.background_color='white'
	pdfimage.alpha_channel='remove'
	pdfimage.format = 'png'
	return len(pdfimage.sequence)

def addMissingPageOverlay(overlay, page):
	from wand.image import Image
	with Image(background='black', height=page.height, width=page.width) as missingOverlay:
		centeredText(missingOverlay, "MISSING\nPAGE")
		overlay.sequence.append(missingOverlay)

def visualEqual(a, b, outputdiff=None, **params):
	"""Returns true if both pdf files a and b are
	pixel identical.

	If outputdiff is provided, a side by side
	pdf will be generated with the differences
	encircled in red.

	TODO: Pass as params things like metric,
	raster resolution, 
	"""

	from wand.display import display
	from wand.image import Image
	from wand.color import Color

	hasdifferences = False
	step("Comparing pdfs")
	step(" Loading pdfs")

	# An overlay for every page to mark pixel differences
	with Image() as overlay:
		overlay.alpha_channel='set'

		with \
				Image(filename=str(a)) as aimage,\
				Image(filename=str(b)) as bimage:

			step(" Rasterizing pdfs")
			nPagesA = rasterize(aimage)
			nPagesB = rasterize(bimage)

			if nPagesA != nPagesB:
				hasdifferences=True
				if not outputdiff:
					warn("Number of pages differ: {} has {} while {} has {}", a, nPagesA, b, nPagesB)
					return False

			for i in range(min(nPagesA,nPagesB)):
				step(" Page {}", i)
				with \
						aimage.sequence[i] as apage, \
						bimage.sequence[i] as bpage  \
						:
					diffpage, ndiffs = apage.compare(bpage,
						metric='absolute',
						highlight='white',
						lowlight='black',
						)
					with diffpage:
						# Not generating outputdiff? be expeditive
						if not outputdiff:
							if ndiffs: return False
							continue

						if ndiffs:
							hasdifferences=True
							warn("Page {} contains {:,.0f} different pixels", i, ndiffs)
							highlightDifferences(diffpage)
						if not ndiffs:
							centeredText(diffpage, "NO DIFFERENCES")

						overlay.sequence.append(diffpage)



			for i in range(min(nPagesA,nPagesB),nPagesA):
				warn("Page {} only available in {}", i, a)
				addMissingPageOverlay(overlay, aimage.sequence[i])

			for i in range(min(nPagesA,nPagesB),nPagesB):
				warn("Page {} only available in {}", i, b)
				addMissingPageOverlay(overlay, bimage.sequence[i])

		if not outputdiff: return hasdifferences

		overlay.format='pdf'
		diff_overlay = overlay.make_blob()

		if not hasdifferences: return True
		buildDiffPdf(a,b,diff_overlay,outputdiff)

	return False

def diff(a,b,diff):
	return visualEqual(Path(a), Path(b), diff and Path(diff))

usage="""\
Usage: {} <doc1.pdf> <doc2.pdf> [<diff.pdf>]

Returns 0 if there is no significant visual differences.
Returns 1 if the diferences are found.
Returns other number if an error happens.

If the third argument is provided a side by side diff
pdf is produced with the differences encircled in red.
"""

def main():
	if len(sys.argv)<3:
		fail("Wrong arguments\n{}".format(usage))

	a,b = (Path(x) for x in sys.argv[1:3])
	output = Path(sys.argv[3]) if len(sys.argv)>3 else None

	tmpchanges("start")
	print(visualEqual(a,b,output))
	tmpchanges("end")

if __name__ == '__main__':
	main()



