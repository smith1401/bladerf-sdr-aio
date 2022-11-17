import os
from os import path
from setuptools import setup, find_packages

PACKAGE_NAME = 'bladerfsdraio'
VERSION = '0.9'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Get the long description from the README file
with open(path.join(BASE_DIR, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name=PACKAGE_NAME,
    version=VERSION,
    author='Christoph Schmied',
    url='https://github.com/pyrtlsdr/pyrtlsdr',
    python_requires='>=3',
    description='An asynchronous Python wrapper based on the official bladerf python library from Nuand',
    long_description=long_description,
    classifiers=['Development Status :: 4 - Beta',
                 'Environment :: Console',
                 'Intended Audience :: Developers',
                 'License :: OSI Approved :: MIT License',
                 'Natural Language :: English',
                 'Operating System :: OS Independent',
                 'Programming Language :: Python :: 3.7',
                 'Programming Language :: Python :: 3.8',
                 'Programming Language :: Python :: 3.9',
                 'Programming Language :: Python :: 3.10',
                 'Topic :: Utilities'],
    license='MIT',
    keywords='bladerf sdr cffi radio libbladerf asyncio',
    platforms=['any'],
    install_requires=['cffi', 'bladerf'],
    packages=find_packages(exclude=['tests*']))
