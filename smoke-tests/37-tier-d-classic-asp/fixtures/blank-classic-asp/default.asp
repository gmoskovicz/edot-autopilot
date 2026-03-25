<%@ Language="VBScript" CodePage="65001" %>
<%
'================================================================
' FILE:        default.asp
' DESCRIPTION: Legacy insurance quote form (Classic ASP / VBScript)
'              Collects applicant data via HTTP POST, runs
'              underwriting rules, stores quote in SQL Server,
'              returns premium to browser.
'
' APP SERVER:  IIS 6.0 / Windows Server 2003
' DB:          SQL Server 2008 — InsuranceDB
' DEPLOYED:    /inetpub/wwwroot/insurance/
'================================================================

Option Explicit
Response.Buffer = True

'-- Database connection string (DSN-less)
Const DB_CONN = "Provider=SQLOLEDB;Server=SQL-PROD-01;Database=InsuranceDB;" & _
                "Integrated Security=SSPI;Application Name=QuoteForm"

'-- Session / request data
Dim strSessionID : strSessionID = Request.Cookies("ASPSESSIONID")
If strSessionID = "" Then strSessionID = "SESS-" & Right(Now(), 8)

Dim strApplicant  : strApplicant  = Request.Form("applicant_name")
Dim intAge        : intAge        = CInt(Request.Form("age"))
Dim strZip        : strZip        = Request.Form("zip_code")
Dim strCoverage   : strCoverage   = Request.Form("coverage_type")
Dim intVehicleYr  : intVehicleYr  = 0
Dim intAnnualMi   : intAnnualMi   = 0
Dim lngHomeValue  : lngHomeValue  = 0
Dim intYearBuilt  : intYearBuilt  = 0

If strCoverage = "auto" Then
    intVehicleYr = CInt(Request.Form("vehicle_year"))
    intAnnualMi  = CInt(Request.Form("annual_miles"))
ElseIf strCoverage = "homeowner" Then
    lngHomeValue = CLng(Request.Form("home_value"))
    intYearBuilt = CInt(Request.Form("year_built"))
End If

'================================================================
' SUB: ConnectDB — returns open ADODB.Connection
'================================================================
Function ConnectDB()
    Dim conn : Set conn = Server.CreateObject("ADODB.Connection")
    conn.Open DB_CONN
    Set ConnectDB = conn
End Function

'================================================================
' FUNCTION: GetRatingFactors — lookup underwriting factors from DB
'================================================================
Function GetRatingFactors(coverage, zip)
    Dim conn  : Set conn  = ConnectDB()
    Dim rs    : Set rs    = Server.CreateObject("ADODB.Recordset")
    Dim sql   : sql = "SELECT zip_territory, base_rate, risk_modifier " & _
                      "FROM RatingFactors " & _
                      "WHERE coverage_type = '" & coverage & "' " & _
                      "  AND zip_prefix    = LEFT('" & zip & "', 3)"
    rs.Open sql, conn

    Dim factors(2)
    If Not rs.EOF Then
        factors(0) = rs("zip_territory")
        factors(1) = rs("base_rate")
        factors(2) = rs("risk_modifier")
    Else
        factors(0) = "STANDARD"
        factors(1) = 1.0
        factors(2) = 1.0
    End If

    rs.Close
    conn.Close
    Set rs   = Nothing
    Set conn = Nothing
    GetRatingFactors = factors
End Function

'================================================================
' FUNCTION: RunUnderwritingRules — calculate annual premium
'================================================================
Function RunUnderwritingRules(coverage, age, homeValue, vehicleYear)
    Dim basePremium : basePremium = 1200
    If coverage = "homeowner" Then basePremium = 1800

    Dim ageFactor : ageFactor = 1.0
    If age < 25 Then ageFactor = 1.0 + (25 - age) * 0.02

    Dim vehicleFactor : vehicleFactor = 1.0
    If coverage = "auto" Then
        vehicleFactor = 1.0 + (2026 - vehicleYear) * 0.015
    End If

    Dim propertyFactor : propertyFactor = 1.0
    If coverage = "homeowner" And homeValue > 0 Then
        propertyFactor = 1.0 + (homeValue - 300000) / 1000000.0
    End If

    RunUnderwritingRules = basePremium * ageFactor * vehicleFactor * propertyFactor
End Function

'================================================================
' SUB: SaveQuote — write approved quote to database
'================================================================
Function SaveQuote(sessionID, applicant, coverage, premium)
    Dim quoteID : quoteID = "QT-" & Format(Now(), "YYYYMMDDHHNNSS")
    Dim conn    : Set conn = ConnectDB()
    Dim sql : sql = "INSERT INTO Quotes " & _
                    "(quote_id, session_id, applicant_name, coverage_type, annual_premium, created_dt) " & _
                    "VALUES ('" & quoteID & "', '" & sessionID & "', '" & _
                    applicant & "', '" & coverage & "', " & premium & ", GETDATE())"
    conn.Execute sql
    conn.Close
    Set conn = Nothing
    SaveQuote = quoteID
End Function

'================================================================
' MAIN — process form submission
'================================================================
Dim annualPremium : annualPremium = 0
Dim quoteID       : quoteID       = ""

If Request.ServerVariables("REQUEST_METHOD") = "POST" Then
    ' Step 1: Fetch rating factors from DB
    Dim factors : factors = GetRatingFactors(strCoverage, strZip)

    ' Step 2: Run underwriting rules
    annualPremium = RunUnderwritingRules(strCoverage, intAge, lngHomeValue, intVehicleYr)
    annualPremium = annualPremium * CDbl(factors(2))   ' apply risk modifier

    ' Step 3: Save quote to database
    quoteID = SaveQuote(strSessionID, strApplicant, strCoverage, annualPremium)

    ' Step 4: Log result to Application EventLog
    Dim wsh : Set wsh = Server.CreateObject("WScript.Shell")
    wsh.LogEvent 4, "QuoteForm: session=" & strSessionID & " quote=" & quoteID & _
                     " coverage=" & strCoverage & " premium=" & FormatCurrency(annualPremium)
    Set wsh = Nothing
End If
%>
<!DOCTYPE html>
<html>
<head><title>Insurance Quote</title></head>
<body>
<h1>Get an Insurance Quote</h1>
<% If quoteID <> "" Then %>
  <div class="quote-result">
    <h2>Your Quote</h2>
    <p>Quote ID: <strong><%= quoteID %></strong></p>
    <p>Coverage: <strong><%= strCoverage %></strong></p>
    <p>Annual Premium: <strong><%= FormatCurrency(annualPremium) %></strong></p>
  </div>
<% Else %>
  <form method="POST" action="default.asp">
    <label>Name: <input type="text" name="applicant_name" /></label><br/>
    <label>Age:  <input type="number" name="age" /></label><br/>
    <label>Zip:  <input type="text" name="zip_code" /></label><br/>
    <label>Coverage:
      <select name="coverage_type">
        <option value="auto">Auto</option>
        <option value="homeowner">Homeowner</option>
      </select>
    </label><br/>
    <label>Vehicle Year: <input type="number" name="vehicle_year" /></label><br/>
    <label>Annual Miles: <input type="number" name="annual_miles" /></label><br/>
    <label>Home Value:   <input type="number" name="home_value" /></label><br/>
    <label>Year Built:   <input type="number" name="year_built" /></label><br/>
    <input type="submit" value="Get Quote" />
  </form>
<% End If %>
</body>
</html>
