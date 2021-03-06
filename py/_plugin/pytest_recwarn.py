"""
helpers for asserting deprecation and other warnings. 

Example usage 
---------------------

You can use the ``recwarn`` funcarg to track 
warnings within a test function:

.. sourcecode:: python

    def test_hello(recwarn):
        from warnings import warn
        warn("hello", DeprecationWarning)
        w = recwarn.pop(DeprecationWarning)
        assert issubclass(w.category, DeprecationWarning)
        assert 'hello' in str(w.message)
        assert w.filename
        assert w.lineno

You can also call a global helper for checking
taht a certain function call yields a Deprecation
warning:

.. sourcecode:: python

    import py
            
    def test_global():
        py.test.deprecated_call(myfunction, 17)
        
        
"""

import py
import os

def pytest_funcarg__recwarn(request):
    """Return a WarningsRecorder instance that provides these methods:

    * ``pop(category=None)``: return last warning matching the category.
    * ``clear()``: clear list of warnings 
    """
    warnings = WarningsRecorder()
    request.addfinalizer(warnings.finalize)
    return warnings

def pytest_namespace():
    return {'deprecated_call': deprecated_call}

def deprecated_call(func, *args, **kwargs):
    """ assert that calling func(*args, **kwargs)
        triggers a DeprecationWarning. 
    """ 
    warningmodule = py.std.warnings
    l = []
    oldwarn_explicit = getattr(warningmodule, 'warn_explicit')
    def warn_explicit(*args, **kwargs): 
        l.append(args) 
        oldwarn_explicit(*args, **kwargs)
    oldwarn = getattr(warningmodule, 'warn')
    def warn(*args, **kwargs): 
        l.append(args) 
        oldwarn(*args, **kwargs)
        
    warningmodule.warn_explicit = warn_explicit
    warningmodule.warn = warn
    try:
        ret = func(*args, **kwargs)
    finally:
        warningmodule.warn_explicit = warn_explicit
        warningmodule.warn = warn
    if not l:
        #print warningmodule
        __tracebackhide__ = True
        raise AssertionError("%r did not produce DeprecationWarning" %(func,))
    return ret


class RecordedWarning:
    def __init__(self, message, category, filename, lineno, line):
        self.message = message
        self.category = category
        self.filename = filename
        self.lineno = lineno
        self.line = line

class WarningsRecorder:
    def __init__(self):
        warningmodule = py.std.warnings
        self.list = []
        def showwarning(message, category, filename, lineno, line=0):
            self.list.append(RecordedWarning(
                message, category, filename, lineno, line))
            try:
                self.old_showwarning(message, category, 
                    filename, lineno, line=line)
            except TypeError:
                # < python2.6 
                self.old_showwarning(message, category, filename, lineno)
        self.old_showwarning = warningmodule.showwarning
        warningmodule.showwarning = showwarning

    def pop(self, cls=Warning):
        """ pop the first recorded warning, raise exception if not exists."""
        for i, w in enumerate(self.list):
            if issubclass(w.category, cls):
                return self.list.pop(i)
        __tracebackhide__ = True
        assert 0, "%r not found in %r" %(cls, self.list)

    #def resetregistry(self):
    #    import warnings
    #    warnings.onceregistry.clear()
    #    warnings.__warningregistry__.clear()

    def clear(self): 
        self.list[:] = []

    def finalize(self):
        py.std.warnings.showwarning = self.old_showwarning
