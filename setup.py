from setuptools import setup
import versioneer


setup(
      cmdclass=versioneer.get_cmdclass()
)
