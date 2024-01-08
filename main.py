#!/usr/bin/env python
# -*- coding: utf-8 -*-

#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License along
#   with this program; if not, write to the Free Software Foundation, Inc.,
#   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""
SYNOPSIS

    python main.py [-h,--help] [-l,--log] [--debug]

DESCRIPTION

    A python script that reads exif data from an image file and saves a copy of the file with a footer displaying date and location information.

EXAMPLES

    python main.py -i /path/to/input/folder -o /path/to/output/folder

AUTHOR

    Robert Crouch (rob.crouch@gmail.com)

VERSION

    $Id$
"""

__program__ = "photo-info-footer"
__author__ = "Robert Crouch (rob.crouch@gmail.com)"
__copyright__ = "Copyright (C) 2023- Robert Crouch"
__license__ = "AGPL-3.0"
__version__ = "v0.20240108"

import os
import sys
import argparse
import logging, logging.handlers
from datetime import datetime
import re

from geopy.geocoders import Nominatim
from geopy.exc import (
    GeocoderServiceError,
    GeocoderTimedOut,
    GeocoderUnavailable,
)

import configobj
from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ExifTags,
)
from icecream import ic

def dms_to_decimal(dms, ref):
    degrees, minutes, seconds = dms
    result = degrees + minutes/60 + seconds/3600
    if ref in ['S', 'W']:
        result = -result
    return result

class App(object):
    """ The main class of your application
    """

    def __init__(self, log, args, config):
        self.log = log
        self.args = args
        self.config = config
        self.version = "{}: {}".format(__program__, __version__)

        self.log.info(self.version)
        if self.args.debug:
            print(self.version)

    def get_image_files(self) -> list:
        """ Read in all the image files from the input folder and return them as a list which includes the full path to the file
        """

        # get the list of files in the input folder
        files = os.listdir(self.args.input)

        # loop through the files and remove any that aren't images
        for f in files:
            if not f.lower().endswith((".jpg", ".jpeg")):
                files.remove(f)

        # prepend the full path to the files
        files = [os.path.join(self.args.input, f) for f in files]
        files.sort()

        return files

    def process_images(self):
        """ Process all the images in the input folder
        """

        # get the list of files to process
        files = self.get_image_files()

        # loop through the files
        for filename in files:
            # Check that the filaname doesn't already exist in the output directory
            if not self.args.overwrite and os.path.exists(os.path.join(self.args.output, os.path.basename(filename))):
                pass
            else:
                img, date_string, location_string = self.process_image(filename)
                ic((filename, date_string, location_string))
                if date_string:
                    self.add_footer(filename, img, date_string, location_string)

    def process_image(self, filename):
        """ Uses PIL to read the exif data from the image file, then adds a footer to the image listing the date and location. The location string is converted from the coordinates in the exif data to a human readable string using the geopy library.
        """

        # Open the image file
        img = Image.open(filename)

        # Get the exif data
        exif_data = img._getexif()

        latitude = None
        longitude = None
        date_string = None
        location_string = None

        if not exif_data:
            return img, date_string, location_string

        # Get the tag name for 'DateTimeOriginal' and 'GPSInfo'
        for tag, value in exif_data.items():
            tagname = ExifTags.TAGS.get(tag, tag)

            # rotate the photo if required
            if tagname == 'Orientation':
                if value == 3:
                    img = img.rotate(180, expand=True)
                elif value == 6:
                    img = img.rotate(270, expand=True)
                elif value == 8:
                    img = img.rotate(90, expand=True)

            # If the tag name is 'DateTimeOriginal', store its value in 'date_string' in the format 'Jan 2018'
            if tagname == 'DateTimeOriginal':
                try:
                    date_string = datetime.strptime(value, "%Y:%m:%d %H:%M:%S").strftime("%b %Y")
                except ValueError as exc:
                    date_string = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%b %Y")
                except:
                    ic(filename)
                    ic(value)
            
            if date_string is None:
                if tagname == 'DateTime':
                    try:
                        date_string = datetime.strptime(value, "%Y:%m:%d %H:%M:%S").strftime("%b %Y")
                    except ValueError as exc:
                        date_string = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%b %Y")
                    except:
                        ic(filename)
                        ic(value)
            
            if date_string is None:
                # use regex check for a date in the filename in format 20180520_093724
                pattern = re.compile(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})')
                match = pattern.search(filename)
                if match:
                    date_string = datetime.strptime(match.group(0), "%Y%m%d_%H%M%S").strftime("%b %Y")

            # If the tag name is 'GPSInfo', store its value in 'gps_data'
            if tagname == 'GPSInfo':
                gps_data = value

                # Get the latitude and longitude
                latitude_dms = gps_data.get(2)
                longitude_dms = gps_data.get(4)
                latitude_ref = gps_data.get(1)
                longitude_ref = gps_data.get(3)

                if latitude_dms and longitude_dms and latitude_ref and longitude_ref:
                    # Convert the latitude and longitude to decimal degrees
                    latitude = dms_to_decimal(latitude_dms, latitude_ref)
                    longitude = dms_to_decimal(longitude_dms, longitude_ref)
                else:
                    if self.args.debug:
                        ic(filename)
                        ic(gps_data)
                    return img, date_string, None

                # Use geopy to convert the coordinates into a location
                geolocator = Nominatim(user_agent="photo-info-footer")
                try:
                    location = geolocator.reverse([latitude, longitude], exactly_one=True)
                except (GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable) as exc:
                    ic(exc)
                    return self.process_image(filename)
                
                if location:
                    location_string_priority = ['tourism', 'hamlet', 'suburb', 'town', 'municipality', 'city_district', 'city']
                    for p in location_string_priority:
                        if p in location.raw['address'].keys():
                            location_string = location.raw['address'][p]
                            break
                    if not location_string:
                        location_string = location.raw['address']['country']

                    if not location_string:
                        ic(filename)
                        ic(location.raw['address'])

        return img, date_string, location_string

    def add_footer(self, filename, img, date_string, location_string):
        """ Adds a footer with white text on a black background to the image listing the date and location
        """

        # Defaults:
        footer_height = 150
        transparency = 150

        # Get the width and height of the image
        width, height = img.size

        # The footer height should be 3% of the image height
        footer_height = int(height * 0.03)

        # The text size should be 80% of the footer height
        text_size = int(footer_height * 0.8)

        # Create a semi-transparent rectangle
        rectangle = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(rectangle)
        draw.rectangle([(0, height - footer_height), (width, height)], fill=(0, 0, 0, transparency))

        # Composite the rectangle onto the image
        img = Image.alpha_composite(img.convert('RGBA'), rectangle)

        # The text should have a left margin of 1% of the image width
        text_x = int(width * 0.01)
        text_y = height - footer_height

        if location_string:
            text = f"{date_string} > {location_string}"
        else:
            text = date_string
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default(text_size)

        # Draw the text onto the image
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

        # Convert the image back to RGB mode before saving
        img = img.convert("RGB")

        # Save the new image out to the output folder
        img.save(os.path.join(self.args.output, os.path.basename(filename)))


def parse_args(argv):
    """ Read in any command line options and return them
    """

    # Define and parse command line arguments
    parser = argparse.ArgumentParser(description=__program__)
    parser.add_argument("--logfile", help="file to write log to", default="%s.log" % __program__)
    parser.add_argument("--configfile", help="use a different config file", default="config.ini")
    parser.add_argument("--debug", action='store_true', default=False)
    parser.add_argument("--overwrite", action='store_true', default=False)
    parser.add_argument("--input", "-i", help="folder to read images from", default="input")
    parser.add_argument("--output", "-o", help="folder to output processed images to", default="output")

    # uncomment this if you want to force at least one command line option
    # if len(sys.argv)==1:
    #   parser.print_help()
    #   sys.exit(1)

    args = parser.parse_args()

    return args

def setup_logging(args):
    """ Everything required when the application is first initialized
    """

    basepath = os.path.abspath(".")

    # set up all the logging stuff
    LOG_FILENAME = os.path.join(basepath, "%s" % args.logfile)

    if args.debug:
        LOG_LEVEL = logging.DEBUG
    else:
        LOG_LEVEL = logging.INFO  # Could be e.g. "DEBUG" or "WARNING"

    # Configure logging to log to a file, making a new file at midnight and keeping the last 3 day's data
    # Give the logger a unique name (good practice)
    log = logging.getLogger(__name__)
    # Set the log level to LOG_LEVEL
    log.setLevel(LOG_LEVEL)
    # Make a handler that writes to a file, making a new file at midnight and keeping 3 backups
    handler = logging.handlers.TimedRotatingFileHandler(LOG_FILENAME, when="midnight", backupCount=3)
    # Format each log message like this
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    # Attach the formatter to the handler
    handler.setFormatter(formatter)
    # Attach the handler to the logger
    log.addHandler(handler)

def main(raw_args):
    """ Main entry point for the script.
    """

    # call function to parse command line arguments
    args = parse_args(raw_args)

    # setup logging
    setup_logging(args)

    # connect to the logger we set up
    log = logging.getLogger(__name__)

    if not os.path.isfile(args.configfile):
        config = configobj.ConfigObj()
        config.filename = args.configfile

        config['footer-height'] = 40 # height of the footer in pixels
        config.write()

    # try to read in the config
    try:
        config = configobj.ConfigObj(args.configfile)

    except (IOError, KeyError, AttributeError) as e:
        print("Unable to successfully read config file: %s" % args.configfile)
        sys.exit(0)

    # fire up our base class and get this app cranking!
    app = App(log, args, config)

    # things that the app does go here:
    app.process_images()

    pass

if __name__ == '__main__':
    sys.exit(main(sys.argv))