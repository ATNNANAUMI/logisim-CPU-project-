/* BASIC: tynix/bin/basic.c run on a built-in session (the lines a user would type),
   under gcc and under tiny C: the same text must come out. Floats stay to what
   32-bit arithmetic gives the same in both (no sin/cos/exp). */
#define BASIC_TEST
#include "../../../../tynix/bin/basic.c"

static const char *session[] = {
    "10 REM sums and loops",
    "20 S = 0",
    "30 FOR I = 1 TO 10",
    "40 S = S + I * I",
    "50 NEXT I",
    "60 PRINT \"sum of squares\"; S",
    "70 FOR J = 10 TO 1 STEP -3 : PRINT J; : NEXT J : PRINT",
    "80 X = 7 : IF X > 5 THEN PRINT \"big\" ELSE PRINT \"small\"",
    "90 IF X < 5 THEN PRINT \"small\" ELSE PRINT \"not small\"",
    "100 GOSUB 500 : GOSUB 500",
    "110 PRINT A$, LEN(A$), \"x\"",
    "120 DIM T(5), N$(3)",
    "130 FOR I = 0 TO 5 : T(I) = I * 1.5 : NEXT",
    "140 N$(0) = \"zero\" : N$(1) = \"one\" : N$(2) = \"two\"",
    "150 PRINT T(4); N$(2); N$(3); \"|\"",
    "160 I = 0 : WHILE I < 3 : J = 0 : WHILE J < 2 : PRINT I * 10 + J; : J = J + 1 : WEND : I = I + 1 : WEND : PRINT",
    "170 READ A, B$, C : PRINT A; B$; C",
    "180 READ A, B$, C : PRINT A; B$; C",
    "190 RESTORE : READ A : PRINT A",
    "200 DATA 1, hello, 2.5",
    "210 DATA 7, \"a, b\", -3",
    "220 PRINT LEFT$(\"abcdef\", 2); RIGHT$(\"abcdef\", 2); MID$(\"abcdef\", 3, 2); MID$(\"abcdef\", 5)",
    "230 PRINT CHR$(65); ASC(\"a\"); STR$(12.5); VAL(\"3.25\") + 1",
    "240 PRINT 7 MOD 3; 2 ^ 10; INT(-2.5); ABS(-4); SQR(81); SGN(-9); 10 / 4",
    "250 PRINT (1 < 2) ; (2 < 1) ; (\"a\" < \"b\") ; (3 = 3) AND (4 <> 4) ; NOT 0 ; 5 OR 2 ; 6 AND 3",
    "260 PRINT \"a\" + \"b\" + \"c\" , 1 , 2",
    "270 INPUT \"name\"; NM$ : INPUT N : PRINT NM$; N * 2",
    "280 GOTO 600",
    "290 PRINT \"never\"",
    "500 A$ = A$ + \"ab\" : RETURN",
    "600 PRINT \"done\" : END",
    "RUN",
    "Ada",
    "21",
    "LIST 100-120",
    "LIST 600",
    "PRINT 2 + 3 * 4",
    "X = 5 : PRINT X",
    "PRINT 1 / 0",
    "PRINT \"a\" + 1",
    "GOTO 999",
    "PRINT FOO",
    "PRINT (1",
    "FOR K = 1 TO 3 : PRINT K; : NEXT K : PRINT",
    "NEXT",
    "RETURN",
    "READ Q",
    "DIM Z(2) : Z(3) = 1",
    "300 PRINT \"edit\"",
    "300",
    "NEW",
    "LIST",
    "10 PRINT \"x\" : PRINT 1 / 0",
    "RUN",
    "BYE",
    0
};
static int next;

static char *scripted(char *buf, int size)
{
    const char *l = session[next];
    if (!l)
        return 0;
    next++;
    strncpy(buf, l, size - 1);
    buf[size - 1] = 0;
    return buf;
}

int main(void)
{
    get_line = scripted;
    basic_loop(0);
    return 0;
}
