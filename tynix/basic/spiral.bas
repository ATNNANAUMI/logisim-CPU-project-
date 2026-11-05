10 REM a spiral on the RGB screen
20 CLS
30 FOR A = 0 TO 60 STEP 0.05
40 R = A * 2
50 X = 128 + R * COS(A) : Y = 128 + R * SIN(A)
60 PLOT X, Y, 1 + INT(A) MOD 14
70 NEXT A
80 TEXT 4, 4, "spiral", 15
