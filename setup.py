from setuptools import setup

setup(
    name='wallhaven',
    version='0.1',
    py_modules=['wallhaven'],
    install_requires=[
        'Click==7.0',
        'requests==2.22.0',
    ],
    entry_points='''
        [console_scripts]
        wallhaven=wallhaven:cli
    ''',
)