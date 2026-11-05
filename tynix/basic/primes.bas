10 REM primes up to N by trial division
20 INPUT "up to"; N
30 FOR I = 2 TO N
40 P = -1 : D = 2
50 WHILE D * D <= I AND P
60 IF I MOD D = 0 THEN P = 0
70 D = D + 1
80 WEND
90 IF P THEN PRINT I;
100 NEXT I
110 PRINT
