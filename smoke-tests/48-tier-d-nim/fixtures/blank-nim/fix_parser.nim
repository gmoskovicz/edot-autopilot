# ================================================================
# FILE:       fix_parser.nim
# DESCRIPTION: High-throughput FIX 4.4 protocol message parser
#              Parses raw FIX message bytes from TCP socket,
#              normalizes to internal order structure, routes
#              to handler (NewOrderSingle, Cancel, Replace,
#              ExecutionReport).
#
# RUNTIME:    Nim 2.0 (compiled with -d:release)
# PROTOCOL:   FIX 4.4 (Financial Information eXchange)
# TRANSPORT:  TCP sockets (acceptor mode, port 5000)
# LATENCY:    Target < 10 microseconds per message
# ================================================================

import std/[net, tables, times, strutils, strformat, parseutils]

# ---- FIX tag constants --------------------------------------
const
  TAG_BEGIN_STRING   = 8
  TAG_BODY_LENGTH    = 9
  TAG_MSG_TYPE       = 35
  TAG_SENDER_COMPID  = 49
  TAG_TARGET_COMPID  = 56
  TAG_MSG_SEQ_NUM    = 34
  TAG_SENDING_TIME   = 52
  TAG_CL_ORD_ID      = 11
  TAG_ORIG_CL_ORD_ID = 41
  TAG_SYMBOL         = 55
  TAG_SIDE           = 54
  TAG_ORDER_QTY      = 38
  TAG_ORD_TYPE       = 40
  TAG_PRICE          = 44
  TAG_TIME_IN_FORCE  = 59
  TAG_EXEC_TYPE      = 150
  TAG_ORD_STATUS     = 39
  TAG_LEAVES_QTY     = 151
  TAG_CUM_QTY        = 14
  TAG_AVG_PX         = 6
  TAG_CHECK_SUM      = 10

# ---- Order types -----------------------------------------
type
  FIXMsgType* = enum
    mtNewOrderSingle       = "D"
    mtOrderCancelRequest   = "F"
    mtOrderCancelReplace   = "G"
    mtExecutionReport      = "8"
    mtUnknown              = "?"

  OrderSide* = enum
    osBuy  = "1"
    osSell = "2"

  OrderRecord* = object
    clOrdId*   : string
    symbol*    : string
    side*      : OrderSide
    qty*       : int
    price*     : float
    msgType*   : FIXMsgType
    seqNum*    : int
    rawBytes*  : int

  ParseResult* = object
    ok*         : bool
    order*      : OrderRecord
    errorMsg*   : string
    latencyUs*  : float

# ---- FIX parser core -------------------------------------

proc parseFIXMessage*(raw: string): ParseResult =
  ## Parse a raw FIX 4.4 message into an OrderRecord.
  ## Returns ParseResult.ok=false on malformed input.
  let t0 = cpuTime()
  result.ok = false

  # FIX fields are delimited by SOH (ASCII 1) or | in test mode
  let sep = if '\x01' in raw: '\x01' else: '|'
  let fields = raw.split(sep)

  var tags = initTable[int, string]()
  for f in fields:
    if f.len == 0: continue
    let eq = f.find('=')
    if eq < 0: continue
    var tagNum: int
    if parseInt(f[0..<eq], tagNum) > 0:
      tags[tagNum] = f[eq+1..^1]

  # Validate required tags
  if TAG_MSG_TYPE notin tags:
    result.errorMsg = "missing tag 35 (MsgType)"
    result.latencyUs = (cpuTime() - t0) * 1_000_000
    return

  if TAG_CL_ORD_ID notin tags:
    result.errorMsg = "missing tag 11 (ClOrdID)"
    result.latencyUs = (cpuTime() - t0) * 1_000_000
    return

  # Build order record
  var order: OrderRecord
  order.clOrdId  = tags.getOrDefault(TAG_CL_ORD_ID, "")
  order.symbol   = tags.getOrDefault(TAG_SYMBOL, "")
  order.seqNum   = parseInt(tags.getOrDefault(TAG_MSG_SEQ_NUM, "0"))
  order.rawBytes = raw.len

  let msgTypeStr = tags.getOrDefault(TAG_MSG_TYPE, "?")
  case msgTypeStr
  of "D": order.msgType = mtNewOrderSingle
  of "F": order.msgType = mtOrderCancelRequest
  of "G": order.msgType = mtOrderCancelReplace
  of "8": order.msgType = mtExecutionReport
  else:   order.msgType = mtUnknown

  let sideStr = tags.getOrDefault(TAG_SIDE, "1")
  order.side = if sideStr == "2": osSell else: osBuy

  discard parseInt(tags.getOrDefault(TAG_ORDER_QTY, "0"), order.qty)
  discard parseFloat(tags.getOrDefault(TAG_PRICE, "0"), order.price)

  result.ok    = true
  result.order = order
  result.latencyUs = (cpuTime() - t0) * 1_000_000

proc routeToHandler*(order: OrderRecord) =
  ## Route parsed order to appropriate handler.
  case order.msgType
  of mtNewOrderSingle:
    echo fmt"[NEW]     {order.clOrdId}  {order.symbol}  side={order.side}  qty={order.qty}  px={order.price:.2f}"
  of mtOrderCancelRequest:
    echo fmt"[CANCEL]  {order.clOrdId}  {order.symbol}  seq={order.seqNum}"
  of mtOrderCancelReplace:
    echo fmt"[REPLACE] {order.clOrdId}  {order.symbol}  qty={order.qty}  px={order.price:.2f}"
  of mtExecutionReport:
    echo fmt"[EXEC]    {order.clOrdId}  {order.symbol}  qty={order.qty}  px={order.price:.2f}"
  of mtUnknown:
    stderr.writeLine fmt"[WARN] Unknown message type for {order.clOrdId}"

# ================================================================
# MAIN — read FIX messages from stdin (one per line, | delimited)
# ================================================================
when isMainModule:
  var
    totalMessages = 0
    parseErrors   = 0
    totalLatUs    = 0.0

  echo "=== FIX 4.4 Parser starting ==="
  echo "Reading messages from stdin (SOH or | delimited)..."
  echo ""

  for line in stdin.lines:
    if line.len == 0: continue
    inc totalMessages

    let res = parseFIXMessage(line)
    totalLatUs += res.latencyUs

    if not res.ok:
      inc parseErrors
      stderr.writeLine fmt"[ERROR] seq={totalMessages}: {res.errorMsg}"
    else:
      routeToHandler(res.order)

  echo ""
  echo "=== Summary ==="
  echo fmt"Messages processed: {totalMessages}"
  echo fmt"Parse errors:       {parseErrors}"
  if totalMessages > 0:
    echo fmt"Avg latency:        {totalLatUs / totalMessages.float:.2f} us"
