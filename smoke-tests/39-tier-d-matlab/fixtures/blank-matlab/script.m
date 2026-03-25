%% run_vibration_analysis.m
% ================================================================
% DESCRIPTION: Predictive maintenance pipeline for rotating machinery
%              Ingests vibration sensor data (acceleration, g-units),
%              runs FFT frequency analysis, detects bearing fault
%              frequencies (BPFO, BPFI, FTF, BSF), triggers
%              maintenance alert when anomaly confidence > 0.75.
%
% SENSORS:    Accelerometers on pumps, motors, bearings, fans
% PLANT:      Manufacturing Plant 1-3
% SCHEDULE:   Every 15 minutes via cron / Task Scheduler
% OUTPUT:     alerts/ directory + maintenance work orders
% ================================================================

function predictive_maintenance_pipeline(config_file)
%PREDICTIVE_MAINTENANCE_PIPELINE  Main entry point.
%   config_file — path to JSON config with sensor list

if nargin < 1
    config_file = 'sensors_config.json';
end

% Load sensor configuration
cfg = jsondecode(fileread(config_file));
sensors = cfg.sensors;

fprintf('=== Predictive Maintenance Analysis ===\n');
fprintf('Timestamp: %s\n', datestr(now, 'yyyy-mm-dd HH:MM:SS'));
fprintf('Sensors:   %d\n\n', numel(sensors));

total_anomalies = 0;

for k = 1:numel(sensors)
    s = sensors(k);
    [rms_g, anomaly_conf, fault_freq] = analyze_sensor(s);
    is_anomaly = anomaly_conf > 0.75;
    if is_anomaly
        total_anomalies = total_anomalies + 1;
        fprintf('[ALERT] %s — anomaly conf=%.0f%% fault_freq=%.1f Hz\n', ...
            s.sensor_id, anomaly_conf*100, fault_freq);
        trigger_maintenance_alert(s, rms_g, anomaly_conf, fault_freq);
    else
        fprintf('[OK]    %s — rms=%.2f g  conf=%.0f%%\n', ...
            s.sensor_id, rms_g, anomaly_conf*100);
    end
end

fprintf('\n=== Summary ===\n');
fprintf('Sensors analyzed: %d\n', numel(sensors));
fprintf('Anomalies found:  %d\n', total_anomalies);

end % function predictive_maintenance_pipeline

% ================================================================
function [rms_g, anomaly_conf, fault_freq] = analyze_sensor(sensor)
%ANALYZE_SENSOR  Run full signal analysis pipeline for one sensor.

rms_g         = 0;
anomaly_conf  = 0;
fault_freq    = 0;

try
    % --- Step 1: Load sensor data ---
    data = load_sensor_data(sensor);

    % --- Step 2: Compute RMS (overall vibration level) ---
    rms_g = sqrt(mean(data .^ 2));

    % --- Step 3: FFT analysis ---
    [freq_axis, power_spectrum] = compute_fft(data, sensor.sample_hz);

    % --- Step 4: Bearing fault detection ---
    [anomaly_conf, fault_freq] = bearing_fault_detector( ...
        freq_axis, power_spectrum, sensor, rms_g);

catch ME
    fprintf('[ERROR] %s: %s\n', sensor.sensor_id, ME.message);
end

end % function analyze_sensor

% ================================================================
function data = load_sensor_data(sensor)
%LOAD_SENSOR_DATA  Load raw accelerometer samples.
%   In production: reads from NI-DAQ, OSIsoft PI, or shared network path.

n_samples = sensor.samples;
% Simulate sinusoidal vibration with noise
t    = (0:n_samples-1) / sensor.sample_hz;
freq = 60 + randn() * 5;          % dominant shaft frequency
data = sin(2*pi*freq*t) + 0.3*randn(1, n_samples);

end % function load_sensor_data

% ================================================================
function [freq_axis, power_spectrum] = compute_fft(data, sample_hz)
%COMPUTE_FFT  Compute one-sided power spectrum using FFT.

n    = length(data);
Y    = fft(data);
P2   = abs(Y/n) .^ 2;
P1   = P2(1:floor(n/2)+1);
P1(2:end-1) = 2 * P1(2:end-1);

freq_axis      = sample_hz * (0:floor(n/2)) / n;
power_spectrum = P1;

end % function compute_fft

% ================================================================
function [anomaly_conf, fault_freq] = bearing_fault_detector( ...
        freq_axis, power_spectrum, sensor, rms_g)
%BEARING_FAULT_DETECTOR  Identify characteristic bearing fault frequencies.
%   Uses BPFO (ball pass frequency outer race) heuristic.

% Bearing geometry constants (generic 6205-2RS deep groove ball bearing)
n_balls  = 8;
pitch_d  = 38.5;      % mm
ball_d   = 7.94;      % mm
shaft_hz = 29.17;     % assumed shaft speed (1750 RPM)

bpfo = (n_balls / 2) * shaft_hz * (1 - (ball_d/pitch_d));  % ~88 Hz

% Find energy in ±5 Hz band around BPFO
mask = abs(freq_axis - bpfo) < 5;
band_energy  = sum(power_spectrum(mask));
total_energy = sum(power_spectrum) + eps;

fault_freq    = bpfo;
anomaly_conf  = min(1, band_energy / total_energy * 50 + rms_g / 10);

end % function bearing_fault_detector

% ================================================================
function trigger_maintenance_alert(sensor, rms_g, anomaly_conf, fault_freq)
%TRIGGER_MAINTENANCE_ALERT  Write alert to filesystem and print work order.

alert.sensor_id      = sensor.sensor_id;
alert.asset          = sensor.asset;
alert.location       = sensor.location;
alert.rms_g          = rms_g;
alert.anomaly_conf   = anomaly_conf;
alert.fault_freq_hz  = fault_freq;
alert.timestamp      = datestr(now, 'yyyy-mm-ddTHH:MM:SS');
alert.recommended_action = 'Schedule bearing inspection within 72h';

alert_dir  = 'alerts';
if ~exist(alert_dir, 'dir'), mkdir(alert_dir); end

alert_file = fullfile(alert_dir, ...
    sprintf('%s_%s.json', sensor.sensor_id, datestr(now, 'yyyymmddHHMM')));

fid = fopen(alert_file, 'w');
fprintf(fid, '%s\n', jsonencode(alert));
fclose(fid);

fprintf('  -> Alert written: %s\n', alert_file);

end % function trigger_maintenance_alert
