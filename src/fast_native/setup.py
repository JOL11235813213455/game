"""Build Cython extensions.

Run: cd src/cython && python setup.py build_ext --inplace
Then copy the .so/.pyd to src/ for import.
"""
from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np

extensions = [
    Extension(
        "fast_math",
        ["fast_math.pyx"],
        include_dirs=[np.get_include()],
        extra_compile_args=["-O3", "-ffast-math"],
    ),
    Extension(
        "fast_creatures",
        ["fast_creatures.pyx"],
        include_dirs=[np.get_include()],
        extra_compile_args=["-O3", "-ffast-math"],
    ),
    Extension(
        "fast_tiles",
        ["fast_tiles.pyx"],
        include_dirs=[np.get_include()],
        extra_compile_args=["-O3", "-ffast-math"],
    ),
]

setup(
    ext_modules=cythonize(extensions, compiler_directives={
        'language_level': 3,
        'boundscheck': False,
        'wraparound': False,
        'cdivision': True,
    }),
)
