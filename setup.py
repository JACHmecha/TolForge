from setuptools import setup, find_packages

setup(
    name="tolforge",
    version="0.1.0",
    description="Tolerance stack-up analysis tool with a PySide6 desktop GUI",
    author="JACHmecha",
    author_email="",
    packages=find_packages(where="Code"),
    package_dir={"": "Code"},
    python_requires=">=3.10",
    install_requires=[
        "numpy>=1.26,<3",
        "PySide6>=6.6,<7",
        "matplotlib>=3.8,<4",
        "compas>=2.15.1,<3",
        "compas_viewer>=2.0.2,<3",
    ],
    extras_require={
        "dev": ["pytest>=8,<10"],
        "build": ["pyinstaller==6.22.3"],
    },
    entry_points={
        "gui_scripts": ["tolforge=gui.app:main"],
    },
    package_data={
        "gui": [
            "assets/icons/gdt/*.svg",
            "assets/icons/gdt/*.json",
            "assets/icons/gdt/*.md",
        ],
    },
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "License :: OSI Approved :: Apache Software License",
    ],
)
