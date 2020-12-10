from setuptools import setup, find_packages
from glob import glob
import versioneer

# read the contents of your README file
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(name='picframe',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Picture frame viewer powered by raspberry with homeassistant integration',
      long_description=long_description,
      long_description_content_type='text/markdown',
      classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.7',
        'Topic :: Multimedia :: Graphics :: Viewers',
      ],
      keywords='picframe viewer raspberry raspi homeassistant hass',
      url='https://github.com/helgeerbe/picture_frame',
      author='Helge Erbe',
      author_email='helge@erbehome.de',
      license='MIT',
      packages=find_packages(exclude=("test", "oldcode")),
      install_requires=[
        'Pillow',
        'ExifRead',
        'pi3d',
        'PyYAML',
        'paho-mqtt'
      ],
      data_files=[
        ('picframe/config', ['config/configuration_example.yaml']),
        ('picframe/data/fonts', glob('data/fonts/*')),
        ('picframe/data/shaders', glob('data/shaders/*')),
        ('picframe/data', glob('data/*.jpg')),
        ('picframe/examples', glob('examples/*')),
      ],
      entry_points = {
        'console_scripts': ['picture_frame=picframe.picture_frame:main']
      },
      include_package_data=True,
      zip_safe=False)