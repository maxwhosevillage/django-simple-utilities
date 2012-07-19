# coding: utf-8
import re

from django.contrib.admin.util import quote as django_quote, unquote as django_unquote
from django.utils.encoding import force_unicode

def listToDict(aList):
    i = 0
    aDict = {}
    for a in aList:
        aDict[i] = a
        i+=1
    return aDict
    

import Image

def fit(file_path, max_width=None, max_height=None, save_as=None):
    # Open file
    img = Image.open(file_path)

    # Store original image width and height
    w, h = img.size

    # Replace width and height by the maximum values
    w = int(max_width or w)
    h = int(max_height or h)

    # Proportinally resize
    img.thumbnail((w, h), Image.ANTIALIAS)

    # Save in (optional) 'save_as' or in the original path
    img.save(save_as or file_path)

    return True

def quote(url):
    url = django_quote(url)
    return re.sub(r' ', '__', url)

def unquote(url):
    url = re.sub(r'__', ' ', force_unicode(url))
    return django_unquote(url)