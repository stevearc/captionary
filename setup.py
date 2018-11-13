""" Setup file """
from setuptools import setup, find_packages

import os


HERE = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(HERE, "README.rst")).read()

REQUIREMENTS = [
    "paste",
    "pyramid",
    "pyramid_duh",
    "pyramid_tm",
    "requests",
    "transaction",
    "zope.sqlalchemy",
]

EXTRAS = {
    "lint": ["black", "pylint==2.1.1"],
    "dev": ["fabric", "invoke", "waitress", "jinja2"],
}


if __name__ == "__main__":
    setup(
        name="captionary",
        version="develop",
        description="Slack bot for photo caption game",
        long_description=README,
        classifiers=[
            "Programming Language :: Python",
            "Programming Language :: Python :: 3.6",
            "Framework :: Pyramid",
            "License :: OSI Approved :: MIT License",
            "Topic :: Internet :: WWW/HTTP",
        ],
        license="MIT",
        author="Steven Arcangeli",
        author_email="stevearc@stevearc.com",
        url="https://github.com/captionary",
        keywords="",
        platforms="any",
        zip_safe=False,
        include_package_data=True,
        packages=find_packages(),
        entry_points={
            "console_scripts": ["process_queue = captionary.cli:process_queue"],
            "paste.app_factory": ["main = captionary:main"],
        },
        install_requires=REQUIREMENTS,
        tests_require=REQUIREMENTS,
        test_suite="tests",
        extras_require=EXTRAS,
    )
