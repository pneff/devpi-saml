#!/usr/bin/env python
import os

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

__author__ = "Patrice Neff <patrice@squirro.com>"


def get_version(path):
    fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), path, "__init__.py")
    with open(fn) as f:
        for line in f:
            if "__version__" in line:
                parts = line.split("=")
                return parts[1].split('"')[1]


here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, "README.rst")).read()


setup(
    name="devpi-saml",
    long_description=README,
    version=get_version("devpi_saml"),
    author="Patrice Neff",
    author_email="patrice@squirro.com",
    keywords="devpi Single Sign-On login using SAML",
    packages=["devpi_saml"],
    entry_points={"devpi_server": ["devpi-saml = devpi_saml.main"]},
    install_requires=["devpi-server", "pyramid_saml>=0.0.2"],
    include_package_data=True,
    classifiers=[
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
    ],
)
