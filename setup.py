import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="gym_turtlebot3",
    version="0.1.0",
    author="Victor Augusto Kich",
    author_email="victorkich@yahoo.comb.br",
    description="Gym environment for TurtleBot3 burger",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/victorkich/TurtleBot3",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=['gym']
)
