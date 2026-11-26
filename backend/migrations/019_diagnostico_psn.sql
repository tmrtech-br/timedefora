alter table public.console_connection_tests drop constraint console_connection_tests_test_type_check;
alter table public.console_connection_tests add constraint console_connection_tests_test_type_check
  check (test_type in ('discover','pair','psn_auth','connection','video_audio','controls','heartbeat','latency'));
