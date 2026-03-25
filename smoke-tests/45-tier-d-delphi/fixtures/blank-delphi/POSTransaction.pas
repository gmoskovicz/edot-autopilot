unit POSTransaction;
{*================================================================*}
{* UNIT:        POSTransaction                                     *}
{* DESCRIPTION: Point-of-Sale transaction processing              *}
{*              Barcode scan -> inventory lookup -> payment auth   *}
{*              -> receipt print -> Firebird DB commit             *}
{*                                                                 *}
{* DATABASE:    Firebird 3.0 (POSDB.FDB)                          *}
{* HARDWARE:    Barcode scanner (USB-HID), Epson TM-T88VII        *}
{*              Verifone card reader (serial)                      *}
{* DELPHI VER:  11.3 Alexandria                                    *}
{*================================================================*}

interface

uses
  System.SysUtils, System.Classes,
  Data.DB, FireDAC.Comp.Client,
  Vcl.ExtCtrls, Vcl.StdCtrls;

type
  TCartItem = record
    Barcode     : string;
    SKUCode     : string;
    Description : string;
    Quantity    : Integer;
    UnitPrice   : Currency;
    TaxRate     : Double;
  end;

  TTransactionResult = record
    TransactionID : string;
    AuthCode      : string;
    TotalUSD      : Currency;
    TaxUSD        : Currency;
    Approved      : Boolean;
    ErrorMessage  : string;
  end;

  TTransactionForm = class
  private
    FTerminalID  : string;
    FConnection  : TFDConnection;
    FCartItems   : TArray<TCartItem>;

    procedure InitDBConnection;
    function  LookupSKU(const Barcode: string): TCartItem;
    function  AuthorizePayment(const PayMethod: string;
                               Amount: Currency): string;
    procedure PrintReceipt(const TxID: string; const Items: TArray<TCartItem>;
                           Total, Tax: Currency);
    procedure CommitToDatabase(const TxID: string;
                                const Items: TArray<TCartItem>;
                                Total, Tax: Currency; const AuthCode: string);
  public
    constructor Create(const TerminalID: string);
    destructor  Destroy; override;

    procedure AddItemToCart(const Barcode: string; Qty: Integer);
    function  ProcessSale(const PaymentMethod: string): TTransactionResult;
    procedure ClearCart;

    property TerminalID : string read FTerminalID;
    property CartCount  : Integer read (Length(FCartItems));
  end;

implementation

uses
  System.DateUtils, System.StrUtils,
  FireDAC.Stan.Intf, FireDAC.Stan.Option, FireDAC.Phys.IBBase,
  FireDAC.Phys.IB;

{ TTransactionForm }

constructor TTransactionForm.Create(const TerminalID: string);
begin
  inherited Create;
  FTerminalID := TerminalID;
  SetLength(FCartItems, 0);
  InitDBConnection;
end;

destructor TTransactionForm.Destroy;
begin
  if Assigned(FConnection) and FConnection.Connected then
    FConnection.Disconnect;
  FConnection.Free;
  inherited;
end;

procedure TTransactionForm.InitDBConnection;
begin
  FConnection := TFDConnection.Create(nil);
  FConnection.DriverName := 'IB';
  FConnection.Params.Values['Database'] := '\\POS-DB-01\POSDB.FDB';
  FConnection.Params.Values['User_Name'] := 'POS_SVC';
  FConnection.Params.Values['Password']  := '';   {loaded from secure store}
  FConnection.Params.Values['CharacterSet'] := 'UTF8';
  FConnection.LoginPrompt := False;
  FConnection.Connect;
end;

procedure TTransactionForm.AddItemToCart(const Barcode: string; Qty: Integer);
var
  Item : TCartItem;
begin
  Item := LookupSKU(Barcode);
  Item.Quantity := Qty;
  SetLength(FCartItems, Length(FCartItems) + 1);
  FCartItems[High(FCartItems)] := Item;
end;

function TTransactionForm.LookupSKU(const Barcode: string): TCartItem;
{* Query Firebird for SKU details by barcode *}
var
  Qry : TFDQuery;
begin
  Qry := TFDQuery.Create(nil);
  try
    Qry.Connection := FConnection;
    Qry.SQL.Text   :=
      'SELECT sku_code, description, unit_price, tax_rate ' +
      'FROM   inventory ' +
      'WHERE  barcode = :bc';
    Qry.ParamByName('bc').AsString := Barcode;
    Qry.Open;

    if Qry.IsEmpty then
      raise Exception.CreateFmt('Barcode not found: %s', [Barcode]);

    Result.Barcode     := Barcode;
    Result.SKUCode     := Qry.FieldByName('sku_code').AsString;
    Result.Description := Qry.FieldByName('description').AsString;
    Result.UnitPrice   := Qry.FieldByName('unit_price').AsCurrency;
    Result.TaxRate     := Qry.FieldByName('tax_rate').AsFloat;
    Result.Quantity    := 1;
  finally
    Qry.Free;
  end;
end;

function TTransactionForm.AuthorizePayment(const PayMethod: string;
                                            Amount: Currency): string;
{* Send authorization request to Verifone terminal via COM port *}
var
  AuthCode : string;
begin
  { In production: communicate with Verifone/Ingenico via ISO 8583 over RS232 }
  { Simulate authorization delay 150-600ms }
  Sleep(150 + Random(450));

  { Mock auth code for development }
  AuthCode := 'AUTH' + IntToStr(100000 + Random(899999));
  Result   := AuthCode;
end;

procedure TTransactionForm.PrintReceipt(const TxID: string;
                                         const Items: TArray<TCartItem>;
                                         Total, Tax: Currency);
{* Send ESC/POS commands to Epson TM-T88VII *}
var
  i : Integer;
begin
  { In production: send ESC/POS via USB/Serial to printer }
  Writeln('--- RECEIPT ---');
  Writeln('TX: ', TxID);
  Writeln('Terminal: ', FTerminalID);
  for i := 0 to High(Items) do
    Writeln(Format('  %-30s x%d  $%.2f',
      [Items[i].Description, Items[i].Quantity,
       Items[i].Quantity * Items[i].UnitPrice]));
  Writeln(Format('  Tax:   $%.2f', [Tax]));
  Writeln(Format('  TOTAL: $%.2f', [Total]));
  Writeln('---------------');
end;

procedure TTransactionForm.CommitToDatabase(const TxID: string;
                                             const Items: TArray<TCartItem>;
                                             Total, Tax: Currency;
                                             const AuthCode: string);
{* Write transaction and line items to Firebird *}
var
  Qry : TFDQuery;
  i   : Integer;
begin
  FConnection.StartTransaction;
  try
    Qry := TFDQuery.Create(nil);
    try
      Qry.Connection := FConnection;

      { Insert header }
      Qry.SQL.Text :=
        'INSERT INTO transactions (tx_id, terminal_id, total_usd, tax_usd, ' +
        '  auth_code, payment_method, tx_ts) ' +
        'VALUES (:tid, :term, :total, :tax, :auth, :pm, NOW)';
      Qry.ParamByName('tid').AsString   := TxID;
      Qry.ParamByName('term').AsString  := FTerminalID;
      Qry.ParamByName('total').AsCurrency := Total;
      Qry.ParamByName('tax').AsCurrency   := Tax;
      Qry.ParamByName('auth').AsString  := AuthCode;
      Qry.ParamByName('pm').AsString    := 'card';
      Qry.ExecSQL;

      { Insert line items }
      for i := 0 to High(Items) do
      begin
        Qry.SQL.Text :=
          'INSERT INTO transaction_lines (tx_id, line_no, sku_code, qty, unit_price) ' +
          'VALUES (:tid, :ln, :sku, :qty, :price)';
        Qry.ParamByName('tid').AsString  := TxID;
        Qry.ParamByName('ln').AsInteger  := i + 1;
        Qry.ParamByName('sku').AsString  := Items[i].SKUCode;
        Qry.ParamByName('qty').AsInteger := Items[i].Quantity;
        Qry.ParamByName('price').AsCurrency := Items[i].UnitPrice;
        Qry.ExecSQL;
      end;
    finally
      Qry.Free;
    end;
    FConnection.Commit;
  except
    FConnection.Rollback;
    raise;
  end;
end;

function TTransactionForm.ProcessSale(
    const PaymentMethod: string): TTransactionResult;
var
  i         : Integer;
  Subtotal  : Currency;
  TaxTotal  : Currency;
  Total     : Currency;
  TxID      : string;
  AuthCode  : string;
begin
  Result.Approved := False;
  Result.ErrorMessage := '';

  if Length(FCartItems) = 0 then
  begin
    Result.ErrorMessage := 'Cart is empty';
    Exit;
  end;

  { Calculate totals }
  Subtotal := 0;
  TaxTotal := 0;
  for i := 0 to High(FCartItems) do
  begin
    Subtotal := Subtotal + FCartItems[i].Quantity * FCartItems[i].UnitPrice;
    TaxTotal := TaxTotal + FCartItems[i].Quantity * FCartItems[i].UnitPrice
                         * FCartItems[i].TaxRate;
  end;
  Total := Subtotal + TaxTotal;

  { Generate transaction ID }
  TxID := 'TXN-' + FormatDateTime('YYYYMMDDHHNNSSzzz', Now);

  { Authorize payment }
  AuthCode := AuthorizePayment(PaymentMethod, Total);

  { Print receipt }
  PrintReceipt(TxID, FCartItems, Total, TaxTotal);

  { Commit to database }
  CommitToDatabase(TxID, FCartItems, Total, TaxTotal, AuthCode);

  Result.TransactionID := TxID;
  Result.AuthCode      := AuthCode;
  Result.TotalUSD      := Total;
  Result.TaxUSD        := TaxTotal;
  Result.Approved      := True;

  Writeln(Format('[POS] %s %s items=%d total=$%.2f auth=%s',
    [FTerminalID, TxID, Length(FCartItems), Total, AuthCode]));
end;

procedure TTransactionForm.ClearCart;
begin
  SetLength(FCartItems, 0);
end;

end.
