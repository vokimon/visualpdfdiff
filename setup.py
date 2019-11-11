#!/usr/bin/env python
from setuptools import setup, find_packages
from io import open

readme = open('README.md', encoding='utf8').read()

setup(
	name = "b2btest-pdf",
	version = "1.0",
	install_requires=[
		'consolemsg',
		'wand',
		'PyPdf2',
		'pathlib2;python_version<"3.5"',
		],
	description = "Side by side visual comparision differences for PDF documents",
	author = "David Garcia Garzon",
	author_email = "voki@canvoki.net",
	url = 'https://github.com/vokimon/back2back-pdf',
	long_description = readme,
	license = 'GNU General Public License v3 or later (GPLv3+)',
	test_suite = 'b2btest-pdf',
	packages=find_packages(exclude=['*_test']),
	classifiers = [
		'Programming Language :: Python',
		'Programming Language :: Python :: 2',
		'Topic :: Software Development :: Libraries :: Python Modules',
		'Intended Audience :: Developers',
		'Development Status :: 5 - Production/Stable',
		'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
		'Operating System :: OS Independent',
		],
	entry_points={
		'back2back.diff': [
			'pdf=visualpdfdiff.pdfvisualdiff:diff',
			]
		},
	)

