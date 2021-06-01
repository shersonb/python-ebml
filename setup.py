from distutils.core import setup
from Cython.Build import cythonize

setup(
    name='ebml',
    version='0.0.1',
    description='EBML Module',
    author='Brian Sherson',
    author_email='caretaker82@gmail.com',
    url='https://github.com/shersonb/python-ebml',
    packages=['ebml'],
    ext_modules=cythonize("ebml/vint.pyx")
)
