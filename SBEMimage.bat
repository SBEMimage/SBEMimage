@echo off
rem The current directory (where this batch file is located) must be the SBEMimage installation directory.
cd src
IF EXIST ..\Python\ (
	rem Run python installed by NSIS installer.
	..\Python\python.exe SBEMimage.py
) ELSE (
	rem Run system python (path must be in %PATH% environment variable).
	python SBEMimage.py
)
cd..
rem Check if status.dat exists in cfg directory (this means that the program terminated normally.)
cd cfg
IF EXIST status.dat (
rem Console window will be closed automatically.
) ELSE (
cd..
rem Console window will stay open.
cmd /k
)