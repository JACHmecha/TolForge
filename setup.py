from setuptools import setup, find_packages

setup(
    name="tolforge",
    version="0.1.0",
    description="Tolerance stack-up analysis tool with a PySide6 desktop GUI",
    author="JACHmecha",
    author_email="",
    packages=find_packages(where="Code"),
    package_dir={"": "Code"},
    python_requires=">=3.11",
    install_requires=[
        "numpy>=1.26",
        "PySide6>=6.6",
        "matplotlib>=3.8",
    ],
    entry_points={
        "gui_scripts": ["tolforge=gui.app:main"],
    },
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "License :: OSI Approved :: Apache Software License",
    ],
)
