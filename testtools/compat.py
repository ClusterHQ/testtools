# Copyright (c) 2008-2010 testtools developers. See LICENSE for details.

"""Utilities for dealing with stuff in unittest."""


import codecs
import linecache
import locale
import os
import re
import sys
import traceback

__metaclass__ = type
__all__ = [
    'advance_iterator',
    'str_is_unicode',
    'unicode_output_stream',
    ]


if sys.version_info > (3, 0):
    def _u(s):
        """Replacement for u'some string' in Python 3."""
        return s
    _r = ascii
    def _b(s):
        """A byte literal."""
        return s.encode("latin-1")
    advance_iterator = next
    def istext(x):
        return isinstance(x, str)
    def classtypes():
        return (type,)
    str_is_unicode = True
else:
    def _u(s):
        """Use _u('\u1234') over u'\u1234' to avoid Python 3 syntax error"""        
        return (s.replace("\\", "\\\\").replace("\\\\u", "\\u")
            .replace("\\\\U", "\\U").decode("unicode-escape"))
    _r = repr
    def _b(s):
        return s
    advance_iterator = lambda it: it.next()
    def istext(x):
        return isinstance(x, basestring)
    def classtypes():
        import types
        return (type, types.ClassType)
    str_is_unicode = sys.platform == "cli"


def unicode_output_stream(stream):
    """Get wrapper for given stream that writes any unicode without exception

    Characters that can't be coerced to the encoding of the stream, or 'ascii'
    if valid encoding is not found, will be replaced. The original stream may
    be returned in situations where a wrapper is determined unneeded.

    The wrapper only allows unicode to be written, not non-ascii bytestrings,
    which is a good thing to ensure sanity and sanitation.
    """
    if sys.platform == "cli":
        # Best to never encode before writing in IronPython
        return stream
    try:
        writer = codecs.getwriter(stream.encoding or "")
    except (AttributeError, LookupError):
        # GZ 2010-06-16: Python 3 StringIO ends up here, but probably needs
        #                different handling as it doesn't want bytestrings
        return codecs.getwriter("ascii")(stream, "replace")
    if writer.__module__.rsplit(".", 1)[1].startswith("utf"):
        # The current stream has a unicode encoding so no error handler is needed
        return stream
    if sys.version_info > (3, 0):
        # Python 3 doesn't seem to make this easy, handle a common case
        try:
            return stream.__class__(stream.buffer, stream.encoding, "replace",
                stream.newlines, stream.line_buffering)
        except AttributeError:
            pass
    return writer(stream, "replace")    


# The default source encoding is actually "iso-8859-1" until Python 2.5 but
# using non-ascii causes a deprecation warning in 2.4 and it's cleaner to
# treat all versions the same way
_default_source_encoding = "ascii"

# Pattern specified in <http://www.python.org/dev/peps/pep-0263/>
_cookie_search=re.compile("coding[:=]\s*([-\w.]+)").search

def _detect_encoding(lines):
    """Get the encoding of a Python source file from a list of lines as bytes

    This function does less than tokenize.detect_encoding added in Python 3 as
    it does not attempt to raise a SyntaxError when the interpreter would, it
    just wants the encoding of a source file Python has already compiled and
    determined is valid.
    """
    if not lines:
        return _default_source_encoding
    if lines[0].startswith("\xef\xbb\xbf"):
        # Source starting with UTF-8 BOM is either UTF-8 or a SyntaxError
        return "utf-8"
    # Only the first two lines of the source file are examined
    magic = _cookie_search("".join(lines[:2]))
    if magic is None:
        return _default_source_encoding
    encoding = magic.group(1)
    try:
        codecs.lookup(encoding)
    except LookupError:
        # Some codecs raise something other than LookupError if they don't
        # support the given error handler, but not the text ones that could
        # actually be used for Python source code
        return _default_source_encoding
    return encoding


class _EncodingTuple(tuple):
    """A tuple type that can have an encoding attribute smuggled on"""


def _get_source_encoding(filename):
    """Detect, cache and return the encoding of Python source at filename"""
    try:
        return linecache.cache[filename].encoding
    except (AttributeError, KeyError):
        encoding = _detect_encoding(linecache.getlines(filename))
        if filename in linecache.cache:
            newtuple = _EncodingTuple(linecache.cache[filename])
            newtuple.encoding = encoding
            linecache.cache[filename] = newtuple
        return encoding

def _get_exception_encoding():
    """Return the encoding we expect messages from the OS to be encoded in"""
    if os.name == "nt":
        # GZ 2010-05-24: Really want the codepage number instead, the error
        #                handling of standard codecs is more deterministic
        return "mbcs"
    # GZ 2010-05-23: We need this call to be after initialisation, but there's
    #                no benefit in asking more than once as it's a global
    #                setting that can change after the message is formatted.
    return locale.getlocale(locale.LC_MESSAGES)[1] or "ascii"

def _exception_to_text(evalue):
    """Try hard to get a sensible text value out of an exception instance"""
    try:
        return unicode(evalue)
    except KeyboardInterrupt:
        raise
    except:
        pass
    try:
        return str(evalue).decode(_get_exception_encoding(), "replace")
    except KeyboardInterrupt:
        raise
    except:
        pass
    # Okay, out of ideas, let higher level handle it
    return None

# GZ 2010-05-23: This function is huge and horrible and I welcome suggestions
#                on the best way to break it up
def _format_exc_info(eclass, evalue, tb, limit=None):
    """Format a stack trace and the exception information as unicode

    Compatibility function for Python 2 which ensures each component of a
    traceback is correctly decoded according to its origins.

    Based on traceback.format_exception and related functions.
    """
    fs_enc = sys.getfilesystemencoding()
    if tb:
        list = ['Traceback (most recent call last):\n']
        extracted_list = []
        for filename, lineno, name, line in traceback.extract_tb(tb, limit):
            extracted_list.append((
                filename.decode(fs_enc, "replace"),
                lineno,
                name.decode("ascii", "replace"),
                line.decode(_get_source_encoding(filename), "replace")))
        list.extend(traceback.format_list(extracted_list))
    else:
        list = []
    if evalue is None:
        # Is a (deprecated) string exception
        list.append(sclass.decode("ascii", "replace"))
    elif isinstance(evalue, SyntaxError) and len(evalue.args) > 1:
        # Avoid duplicating the special formatting for SyntaxError here,
        # instead create a new instance with unicode filename and line
        # Potentially gives duff spacing, but that's a pre-existing issue
        filename, lineno, offset, line = evalue.args[1]
        if filename:
            filename = filename.decode(fs_enc, "replace")
        if line:
            # Errors during parsing give the line from buffer encoded as
            # latin-1 if the given coding or utf-8 for all other codings
            # Can't know which was used, so just try utf-8 first
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                line = line.decode("latin-1")
        evalue = eclass(evalue.args[0], (filename, lineno, offset, line))
        list.extend(traceback.format_exception_only(eclass, evalue))
    else:
        sclass = eclass.__name__
        svalue = _exception_to_text(evalue)
        if svalue:
            list.append("%s: %s\n" % (sclass, svalue))
        elif svalue is None:
            # GZ 2010-05-24: Not a great fallback message, but keep for the
            #                the same for compatibility for the moment
            list.append("%s: <unprintable %s object>\n" % (sclass, sclass))
        else:
            list.append("%s\n" % sclass)
    return list
