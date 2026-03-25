      **================================================================**
      * PROGRAM:     WHINV001                                          *
      * DESCRIPTION: Warehouse Inventory Cycle Count Reconciliation    *
      *              Reads INVMSTPF inventory master, performs cycle   *
      *              count, writes adjustments to INVADJPF, triggers   *
      *              replenishment orders when stock below reorder pt  *
      *                                                               *
      * LIBRARY:     WHPRDLIB                                          *
      * JOB QUEUE:   WHBATCH                                           *
      * SCHEDULE:    Daily 06:00 before warehouse opens                *
      **================================================================**
      * PROGRAM-ID:  WHINV001
      * AUTHOR:      WAREHOUSE-TEAM
      * DATE:        2024-03-01
      **================================================================**
     FINVMSTPF  IF   E           K DISK
     FINVADJPF  O    E           K DISK
     FRPLORDF   O    E           K DISK

      *-- Data structure for inventory master record
     D InvMstDs        DS
     D  WsItemNum                    12A
     D  WsLocation                    8A
     D  WsSystemQty                  10P 0
     D  WsReorderPt                  10P 0
     D  WsUnitCost                    9P 2
     D  WsDescription                40A

      *-- Work fields
     D WsCountedQty    S             10P 0
     D WsVariance      S             10P 0
     D WsTotalItems    S              7P 0
     D WsAdjCount      S              7P 0
     D WsReplCount     S              7P 0

      *-- Adjustment record
     D AdjDs           DS
     D  AdjItemNum                   12A
     D  AdjLocation                   8A
     D  AdjVariance                  10P 0
     D  AdjDate                       8A
     D  AdjType                       4A

      *-- Replenishment order record
     D RplDs           DS
     D  RplItemNum                   12A
     D  RplLocation                   8A
     D  RplQtyOnHand                 10P 0
     D  RplReorderPt                 10P 0
     D  RplDate                       8A

      *-- Constants
     D CycleDate       C                   CONST('2026-02-28')
     D AdjTypeCC       C                   CONST('CC  ')

      **================================================================**
      * MAIN PROCEDURE                                                  *
      **================================================================**
     C     *ENTRY        PLIST

     C                   EXSR      SR_INIT
     C                   EXSR      SR_PROCESS_ITEMS
     C                   EXSR      SR_WRITE_SUMMARY
     C                   EVAL      *INLR = *ON
     C                   RETURN

      **================================================================**
      * SR_INIT - Initialize counters and open files                   *
      **================================================================**
     C     SR_INIT       BEGSR
     C                   EVAL      WsTotalItems  = 0
     C                   EVAL      WsAdjCount    = 0
     C                   EVAL      WsReplCount   = 0
     C                   DSPLY     'WHINV001 STARTING CYCLE COUNT'
     C                   DSPLY     'DATE: ' + CycleDate
     C                   ENDSR

      **================================================================**
      * SR_PROCESS_ITEMS - Read each item and perform cycle count       *
      **================================================================**
     C     SR_PROCESS_ITEMS BEGSR
     C                   READ      INVMSTPF                            99
     C                   DOW       NOT %EOF(INVMSTPF)
     C                   ADD       1             WsTotalItems
     C                   EVAL      WsItemNum     = InvMstDs.WsItemNum
     C                   EVAL      WsLocation    = InvMstDs.WsLocation
     C                   EVAL      WsSystemQty   = InvMstDs.WsSystemQty
     C                   EVAL      WsReorderPt   = InvMstDs.WsReorderPt
     C                   EXSR      SR_CYCLE_COUNT
     C                   READ      INVMSTPF                            99
     C                   ENDDO
     C                   ENDSR

      **================================================================**
      * SR_CYCLE_COUNT - Perform cycle count for one item               *
      **================================================================**
     C     SR_CYCLE_COUNT BEGSR
      * Physical count simulation (in production, scanner input)
     C                   EVAL      WsCountedQty  = WsSystemQty
     C                   EVAL      WsVariance    = WsCountedQty - WsSystemQty

      * Write adjustment if variance detected
     C                   IF        WsVariance <> 0
     C                   EXSR      SR_WRITE_ADJUSTMENT
     C                   ENDIF

      * Trigger replenishment if stock at or below reorder point
     C                   IF        WsCountedQty <= WsReorderPt
     C                   EXSR      SR_TRIGGER_REPLENISHMENT
     C                   ENDIF

     C                   DSPLY     'ITEM: ' + %TRIM(WsItemNum) +
     C                             ' COUNT: ' + %CHAR(WsCountedQty) +
     C                             ' VAR: ' + %CHAR(WsVariance)
     C                   ENDSR

      **================================================================**
      * SR_WRITE_ADJUSTMENT - Write inventory adjustment record         *
      **================================================================**
     C     SR_WRITE_ADJUSTMENT BEGSR
     C                   EVAL      AdjDs.AdjItemNum  = WsItemNum
     C                   EVAL      AdjDs.AdjLocation = WsLocation
     C                   EVAL      AdjDs.AdjVariance = WsVariance
     C                   EVAL      AdjDs.AdjDate     = CycleDate
     C                   EVAL      AdjDs.AdjType     = AdjTypeCC
     C                   WRITE     INVADJPF          AdjDs
     C                   ADD       1             WsAdjCount
     C                   DSPLY     'ADJUSTMENT WRITTEN: ' + %TRIM(WsItemNum)
     C                   ENDSR

      **================================================================**
      * SR_TRIGGER_REPLENISHMENT - Create replenishment order           *
      **================================================================**
     C     SR_TRIGGER_REPLENISHMENT BEGSR
     C                   EVAL      RplDs.RplItemNum   = WsItemNum
     C                   EVAL      RplDs.RplLocation  = WsLocation
     C                   EVAL      RplDs.RplQtyOnHand = WsCountedQty
     C                   EVAL      RplDs.RplReorderPt = WsReorderPt
     C                   EVAL      RplDs.RplDate      = CycleDate
     C                   WRITE     RPLORDF           RplDs
     C                   ADD       1             WsReplCount
     C                   DSPLY     'REPLENISHMENT TRIGGERED: ' + %TRIM(WsItemNum)
     C                   ENDSR

      **================================================================**
      * SR_WRITE_SUMMARY - Write batch summary to job log               *
      **================================================================**
     C     SR_WRITE_SUMMARY BEGSR
     C                   DSPLY     'WHINV001 CYCLE COUNT COMPLETE'
     C                   DSPLY     'ITEMS COUNTED:    ' + %CHAR(WsTotalItems)
     C                   DSPLY     'ADJUSTMENTS:      ' + %CHAR(WsAdjCount)
     C                   DSPLY     'REPLENISHMENTS:   ' + %CHAR(WsReplCount)
     C                   ENDSR
