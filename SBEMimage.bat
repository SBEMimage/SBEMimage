@echo off
rem Assuming that the current directory is the SBEMimage folder
rem and that the command "python" works.
cd src
python SBEMimage.py
cd..
cd cfg 
IF EXIST status.dat (
rem Console window will be closed
) ELSE (
rem Console window will stay open
cmd /k
)