from setuptools import setup, find_packages
from glob import glob
import versioneer

# read the contents of your README file
import os
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(name='picframe',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Picture frame viewer powered by raspberry with homeassistant integration',
      long_description=long_description,
      long_description_content_type='text/markdown',
      classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.7',
        'Topic :: Multimedia :: Graphics :: Viewers',
      ],
      keywords='picframe viewer raspberry raspi homeassistant hass',
      url='https://github.com/helgeerbe/picframe',
      author='Paddy Gaunt, Jeff Godfrey, Helge Erbe',
      author_email='helge@erbehome.de',
      license='MIT',
      packages=find_packages(exclude=("test")),
      package_data={ '': [
        'data/*', 'data/**/*', 
        'config/*', 'config/**/*', 
        'html/*', 'html/**/*']},
      install_requires=[
        'Pillow',
        'ExifRead',
        'pi3d>=2.44',
        'PyYAML',
        'paho-mqtt',
        'IPTCInfo3',
        'numpy',
        'ninepatch'
      ],
      entry_points = {
        'console_scripts': ['picframe=picframe.start:main']
      },
      include_package_data=True,
      zip_safe=False)
