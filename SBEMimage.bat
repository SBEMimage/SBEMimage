@echo off
rem Assuming that the current directory is the SBEMimage folder
rem and that the command "python" works.
cd src
python SBEMimage.py
rem Use the following (commented out) command instead when building installer (uses bundled Python interpreter)
rem ..\Python\python.exe SBEMimage.py
cd..
cd cfg 
IF EXIST status.dat (
rem Console window will be closed
) ELSE (
cd..
rem Console window will stay open
cmd /k
)