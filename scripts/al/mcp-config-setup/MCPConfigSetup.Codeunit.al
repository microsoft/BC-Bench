namespace BCBench.MCP;

using System.MCP;

// Installed at container-setup time (not part of the benchmarked workspace). Provisions and activates
// the MCP configuration the evaluated agent connects to over the BC MCP server; this app is the single
// place that decides which server capabilities the eval exposes. Idempotent: re-installs reuse the
// existing configuration by name.
codeunit 50150 "BCBench MCP Config Setup"
{
    Subtype = Install;

    trigger OnInstallAppPerCompany()
    begin
        EnsureConfiguration();
    end;

    local procedure EnsureConfiguration()
    var
        MCPConfig: Codeunit "MCP Config";
        ConfigId: Guid;
    begin
        ConfigId := MCPConfig.GetConfigurationIdByName(ConfigNameTok);
        if IsNullGuid(ConfigId) then
            ConfigId := MCPConfig.CreateConfiguration(ConfigNameTok, ConfigDescriptionTok);

        MCPConfig.EnableDataQueryTools(ConfigId, true);
        MCPConfig.ActivateConfiguration(ConfigId, true);
    end;

    var
        ConfigNameTok: Label 'BCBench', Locked = true;
        ConfigDescriptionTok: Label 'BC-Bench evaluation', Locked = true;
}
