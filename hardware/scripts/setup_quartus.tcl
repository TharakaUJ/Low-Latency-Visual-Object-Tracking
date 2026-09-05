set project_dir [file normalize [file dirname [info script]]]
cd $project_dir/..

set fp [open "tests/matcher.f" r]

while {[gets $fp line] >= 0} {
    # Ignore empty lines
    if {[string trim $line] eq ""} {
        continue
    }

    # Ignore comments
    if {[string match "#*" [string trim $line]} {
        continue
    }

    set file [string trim $line]

    set_global_assignment -name SYSTEMVERILOG_FILE $file
}

close $fp