-- ================================================================
-- FILE:       fms_navigation.adb
-- DESCRIPTION: Flight Management System — Navigation Health Monitor
--              Reads IRU (Inertial Reference Unit) and GPS sensor
--              data at 10Hz, computes RNP accuracy, monitors fuel
--              state, and detects autopilot mode transitions.
--
-- PLATFORM:   Avionics DO-178C DAL-C safety level
-- RUNTIME:    GNAT Pro 24.2 (Ada 2022)
-- RTOS:       VxWorks 653 (ARINC 653 partitioned)
-- SCHEDULE:   100ms cyclic task (Navigation_Monitor_Task)
-- ================================================================

with Ada.Text_IO;           use Ada.Text_IO;
with Ada.Float_Text_IO;
with Ada.Integer_Text_IO;
with Ada.Calendar;          use Ada.Calendar;

package body FMS.Navigation_Monitor is

   -- ============================================================
   -- Sensor data types
   -- ============================================================
   type IRU_Data_Type is record
      Heading_Deg      : Float;
      Pitch_Deg        : Float;
      Roll_Deg         : Float;
      Latitude_Deg     : Float;
      Longitude_Deg    : Float;
      Ground_Speed_Kts : Float;
      Valid            : Boolean;
   end record;

   type GPS_Data_Type is record
      Latitude_Deg   : Float;
      Longitude_Deg  : Float;
      Altitude_Ft    : Float;
      Speed_Kts      : Float;
      Track_Deg      : Float;
      HDOP           : Float;   -- Horizontal dilution of precision
      Satellites     : Natural;
      Valid          : Boolean;
   end record;

   type Fuel_State_Type is record
      Left_Wing_Kg   : Float;
      Right_Wing_Kg  : Float;
      Center_Kg      : Float;
      Total_Kg       : Float;
      Flow_KgHr      : Float;
      ETA_Dest_Min   : Natural;
   end record;

   type Nav_Accuracy_Type is record
      RNP_Required_NM : Float;  -- Required Navigation Performance
      EPE_Actual_M    : Float;  -- Estimated Position Error in metres
      Within_RNP      : Boolean;
   end record;

   -- ============================================================
   -- Read_IRU_Data — read inertial reference unit
   -- ============================================================
   procedure Read_IRU_Data
     (Data    : out IRU_Data_Type;
      Valid   : out Boolean)
   is
   begin
      -- In production: read from ARINC 429 bus (labels 310, 311, 312)
      Data := (Heading_Deg      => 275.4,
               Pitch_Deg        =>  -1.2,
               Roll_Deg         =>   0.3,
               Latitude_Deg     =>  40.63,
               Longitude_Deg    => -73.94,
               Ground_Speed_Kts => 487.0,
               Valid             => True);
      Valid := Data.Valid;
   end Read_IRU_Data;

   -- ============================================================
   -- Read_GPS_Data — read GPS receiver data
   -- ============================================================
   procedure Read_GPS_Data
     (Data    : out GPS_Data_Type;
      Valid   : out Boolean)
   is
   begin
      -- In production: read from ARINC 429 bus (labels 150x GPS)
      -- GPS can become invalid during ionospheric interference
      Data := (Latitude_Deg   =>  40.63,
               Longitude_Deg  => -73.94,
               Altitude_Ft    => 37000.0,
               Speed_Kts      => 487.0,
               Track_Deg      => 275.4,
               HDOP           =>   1.2,
               Satellites     =>    10,
               Valid           => True);
      Valid := Data.Valid;
   end Read_GPS_Data;

   -- ============================================================
   -- Compute_RNP_Accuracy — calculate navigation accuracy
   -- ============================================================
   function Compute_RNP_Accuracy
     (IRU_Data : IRU_Data_Type;
      GPS_Data : GPS_Data_Type) return Nav_Accuracy_Type
   is
      RNP_Required : constant Float := 0.3;   -- 0.3 NM (oceanic RNAV)
      EPE_M        : Float;
   begin
      if GPS_Data.Valid then
         -- Compute blended IRU/GPS error estimate
         EPE_M := GPS_Data.HDOP * 5.0;  -- simplified UERE model
      else
         -- GPS invalid — IRU drift model (0.1 NM/hr)
         EPE_M := 50.0;  -- higher uncertainty
      end if;

      return (RNP_Required_NM => RNP_Required,
              EPE_Actual_M    => EPE_M,
              Within_RNP      => EPE_M < (RNP_Required * 1852.0));
   end Compute_RNP_Accuracy;

   -- ============================================================
   -- Compute_Fuel_State — read fuel quantity and compute ETA
   -- ============================================================
   function Compute_Fuel_State
     (Flight_ID : String) return Fuel_State_Type
   is
   begin
      -- In production: read ARINC 429 fuel quantity labels
      return (Left_Wing_Kg  => 10_425.0,
              Right_Wing_Kg => 10_400.0,
              Center_Kg     =>  21_025.0,
              Total_Kg      =>  41_850.0,
              Flow_KgHr     =>   5_200.0,
              ETA_Dest_Min  =>        215);
   end Compute_Fuel_State;

   -- ============================================================
   -- Navigation_Monitor_Task — cyclic monitoring task (100ms)
   -- ============================================================
   task body Navigation_Monitor_Task is
      Cycle_Count   : Natural := 0;
      IRU_Data      : IRU_Data_Type;
      GPS_Data      : GPS_Data_Type;
      Fuel          : Fuel_State_Type;
      Nav_Acc       : Nav_Accuracy_Type;
      IRU_Valid     : Boolean;
      GPS_Valid     : Boolean;
      Has_Warning   : Boolean;
   begin
      Put_Line ("=== FMS Navigation Monitor Starting ===");
      Put_Line ("Flight: " & Flight_Parameters.Flight_ID);
      Put_Line ("Phase:  " & Flight_Parameters.Phase);
      New_Line;

      loop
         Cycle_Count := Cycle_Count + 1;

         -- Step 1: Read IRU data
         Read_IRU_Data (IRU_Data, IRU_Valid);
         if not IRU_Valid then
            Put_Line ("[WARN] IRU data invalid — cycle " &
                      Natural'Image (Cycle_Count));
         end if;

         -- Step 2: Read GPS data
         Read_GPS_Data (GPS_Data, GPS_Valid);
         if not GPS_Valid then
            Put_Line ("[WARN] GPS sensor invalid — reverting to IRU-only nav" &
                      "  cycle=" & Natural'Image (Cycle_Count));
         end if;

         -- Step 3: Compute navigation accuracy
         Nav_Acc := Compute_RNP_Accuracy (IRU_Data, GPS_Data);
         Has_Warning := not Nav_Acc.Within_RNP or not GPS_Valid;

         if not Nav_Acc.Within_RNP then
            Put_Line ("[WARN] RNP exceeded: EPE=" &
                      Float'Image (Nav_Acc.EPE_Actual_M) & "m  flight=" &
                      Flight_Parameters.Flight_ID);
         end if;

         -- Step 4: Compute fuel state
         Fuel := Compute_Fuel_State (Flight_Parameters.Flight_ID);

         -- Step 5: Log cycle summary
         Put ("  Cycle " & Natural'Image (Cycle_Count));
         Put ("  nav_err=" & Float'Image (Nav_Acc.EPE_Actual_M) & "m");
         Put ("  gps=" & Boolean'Image (GPS_Valid));
         Put ("  fuel=" & Float'Image (Fuel.Total_Kg) & "kg");
         Put_Line ("");

         -- Exit after configured cycles (used for batch testing)
         exit when Cycle_Count >= Max_Monitor_Cycles;

         delay 0.1;  -- 100ms cyclic period
      end loop;

      Put_Line ("=== Navigation Monitor complete — " &
                Natural'Image (Cycle_Count) & " cycles ===");
   end Navigation_Monitor_Task;

end FMS.Navigation_Monitor;
