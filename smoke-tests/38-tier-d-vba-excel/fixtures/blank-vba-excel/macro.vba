' ================================================================
' MODULE:      ConsolidatePL
' WORKBOOK:    GroupConsolidation_2026Q1.xlsm
' DESCRIPTION: Monthly Group P&L Consolidation Macro
'              Reads each subsidiary P&L workbook, applies FX
'              rates, consolidates into Group P&L sheet, and
'              generates management summary report.
'
' SUBSIDIARIES: EMEA-GmbH (EUR), APAC-Pte (SGD),
'               LATAM-SA (BRL), NA-Corp (USD)
' ================================================================
Option Explicit

' ---- Configuration constants --------------------------------
Private Const BASE_PATH      As String = "\\FINANCE-SRV\Consolidation\2026Q1\"
Private Const TARGET_WB      As String = "GroupConsolidation_2026Q1.xlsm"
Private Const RATE_SHEET     As String = "FX_Rates"
Private Const GROUP_PL_SHEET As String = "Group P&L"

' ---- Data structure for subsidiary info ---------------------
Private Type SubsidiaryInfo
    EntityName  As String
    FileName    As String
    Currency    As String
    FXRate      As Double
    RevenueRow  As Integer
    CogsRow     As Integer
    OpexRow     As Integer
End Type

' ================================================================
' MAIN ENTRY POINT
' ================================================================
Public Sub Macro_ConsolidatePL()
    Dim subs(3) As SubsidiaryInfo
    Dim i       As Integer
    Dim totalRevUSD As Double
    Dim ws      As Worksheet

    ' Define subsidiaries
    subs(0).EntityName = "EMEA-GmbH"  : subs(0).Currency = "EUR"
    subs(0).FileName   = "EMEA-GmbH_PL_2026Q1.xlsx"
    subs(0).RevenueRow = 4 : subs(0).CogsRow = 5 : subs(0).OpexRow = 6

    subs(1).EntityName = "APAC-Pte"   : subs(1).Currency = "SGD"
    subs(1).FileName   = "APAC-Pte_PL_2026Q1.xlsx"
    subs(1).RevenueRow = 4 : subs(1).CogsRow = 5 : subs(1).OpexRow = 6

    subs(2).EntityName = "LATAM-SA"   : subs(2).Currency = "BRL"
    subs(2).FileName   = "LATAM-SA_PL_2026Q1.xlsx"
    subs(2).RevenueRow = 4 : subs(2).CogsRow = 5 : subs(2).OpexRow = 6

    subs(3).EntityName = "NA-Corp"    : subs(3).Currency = "USD"
    subs(3).FileName   = "NA-Corp_PL_2026Q1.xlsx"
    subs(3).RevenueRow = 4 : subs(3).CogsRow = 5 : subs(3).OpexRow = 6

    ' Fetch FX rates from rates sheet
    Call LoadFXRates(subs)

    ' Clear previous consolidation data
    Set ws = ThisWorkbook.Sheets(GROUP_PL_SHEET)
    ws.Range("B4:E20").ClearContents

    totalRevUSD = 0

    ' Process each subsidiary
    For i = 0 To 3
        Call ConsolidateSubsidiary(subs(i), ws, i + 2, totalRevUSD)
    Next i

    ' Write group totals
    Call WriteGroupTotals(ws, totalRevUSD)

    ' Auto-fit and format
    ws.Columns.AutoFit

    MsgBox "Consolidation complete!" & vbCrLf & _
           "Group Revenue (USD): " & Format(totalRevUSD, "#,##0"), _
           vbInformation, "P&L Consolidation"
End Sub

' ================================================================
' LoadFXRates — read FX rates from the FX_Rates sheet
' ================================================================
Private Sub LoadFXRates(ByRef subs() As SubsidiaryInfo)
    Dim ws   As Worksheet
    Dim i    As Integer
    Dim ccy  As String
    Dim row  As Integer

    Set ws = ThisWorkbook.Sheets(RATE_SHEET)

    ' Expected layout: col A = currency code, col B = rate to USD
    For i = 0 To 3
        For row = 2 To 20
            ccy = ws.Cells(row, 1).Value
            If ccy = subs(i).Currency Then
                subs(i).FXRate = CDbl(ws.Cells(row, 2).Value)
                Exit For
            End If
        Next row
        ' Default to 1.0 if not found
        If subs(i).FXRate = 0 Then subs(i).FXRate = 1.0
    Next i
End Sub

' ================================================================
' ConsolidateSubsidiary — open subsidiary workbook, read P&L data,
' apply FX conversion, write to Group P&L sheet
' ================================================================
Private Sub ConsolidateSubsidiary(sub As SubsidiaryInfo, _
                                   wsGroup As Worksheet, _
                                   col As Integer, _
                                   ByRef totalRev As Double)
    Dim wbSub  As Workbook
    Dim wsSub  As Worksheet
    Dim revLC  As Double   ' Revenue in local currency
    Dim cogsLC As Double
    Dim opexLC As Double
    Dim revUSD As Double
    Dim cogsUSD As Double
    Dim opexUSD As Double
    Dim gpUSD  As Double
    Dim ebitUSD As Double

    ' --- Open subsidiary workbook ---
    wbSub = Workbooks.Open(BASE_PATH & sub.FileName, ReadOnly:=True)
    Set wsSub = wbSub.Sheets("P&L")

    ' --- Read P&L lines (column B = period values) ---
    revLC  = CDbl(wsSub.Cells(sub.RevenueRow, 2).Value)
    cogsLC = CDbl(wsSub.Cells(sub.CogsRow, 2).Value)
    opexLC = CDbl(wsSub.Cells(sub.OpexRow, 2).Value)

    ' --- Apply FX conversion ---
    revUSD  = revLC  * sub.FXRate
    cogsUSD = cogsLC * sub.FXRate
    opexUSD = opexLC * sub.FXRate
    gpUSD   = revUSD - cogsUSD
    ebitUSD = gpUSD  - opexUSD

    ' --- Write to Group P&L column ---
    wsGroup.Cells(3, col).Value  = sub.EntityName
    wsGroup.Cells(4, col).Value  = revUSD
    wsGroup.Cells(5, col).Value  = cogsUSD
    wsGroup.Cells(6, col).Value  = gpUSD
    wsGroup.Cells(7, col).Value  = opexUSD
    wsGroup.Cells(8, col).Value  = ebitUSD
    wsGroup.Cells(9, col).Value  = IIf(revUSD > 0, gpUSD / revUSD, 0)

    totalRev = totalRev + revUSD

    ' --- Close subsidiary workbook without saving ---
    wbSub.Close SaveChanges:=False

    Debug.Print "Consolidated: " & sub.EntityName & _
                " Rev=" & Format(revUSD, "#,##0") & " USD" & _
                " EBIT=" & Format(ebitUSD, "#,##0") & " USD"
End Sub

' ================================================================
' WriteGroupTotals — sum columns and write group-level totals
' ================================================================
Private Sub WriteGroupTotals(ws As Worksheet, totalRev As Double)
    Dim lastCol As Integer : lastCol = 5   ' B through E = 4 subsidiaries

    ws.Cells(3, lastCol + 1).Value = "GROUP TOTAL"
    ws.Cells(4, lastCol + 1).Formula = "=SUM(B4:E4)"   ' Revenue
    ws.Cells(5, lastCol + 1).Formula = "=SUM(B5:E5)"   ' COGS
    ws.Cells(6, lastCol + 1).Formula = "=SUM(B6:E6)"   ' Gross Profit
    ws.Cells(7, lastCol + 1).Formula = "=SUM(B7:E7)"   ' OPEX
    ws.Cells(8, lastCol + 1).Formula = "=SUM(B8:E8)"   ' EBIT
    ws.Cells(9, lastCol + 1).Formula = "=F6/F4"        ' GP Margin

    Debug.Print "Group consolidation complete. Total Revenue (USD): " & _
                Format(totalRev, "#,##0")
End Sub
