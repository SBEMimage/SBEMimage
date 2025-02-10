@echo off
rem The current directory (where this batch file is located) must be the SBEMimage installation directory.
IF EXIST Python\ (
	rem Run python installed by NSIS installer.
	Python\python.exe src/sbemimage.py
) ELSE (
	rem Run system python (path must be in %PATH% environment variable).
	python src/sbemimage.py
)
rem Check if status.dat exists in cfg directory (this means that the program terminated normally.)
IF NOT EXIST cfg/status.dat (
	rem Console window will stay open.
	cmd /k
)