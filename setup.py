from setuptools import setup, find_packages
from glob import glob
import versioneer

setup(name='picframe',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Picture frame viewer powered by raspberry with homeassistant integration',
      classifiers=[
        'Development Status :: 3 - Alpha',
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
        'ExifRead',
        'pi3d'
      ],
      data_files=[
        ('picframe/config', ['config/configuration_example.yaml']),
        ('picframe/data', glob('data/*')),
        ('picframe/examples', glob('examples/*')),
      ],
      entry_points = {
        'console_scripts': ['picture_frame=picframe.picture_frame:main']
      },
      include_package_data=True,
      zip_safe=False)