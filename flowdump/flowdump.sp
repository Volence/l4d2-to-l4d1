// flowdump: write the game's own flow distance for every nav area, so l4d2to1/rotoblin.py can place
// ban windows and boss caps in true flow instead of estimating from the nav.
//
//   sm_flowdump                      dump the current map to addons/sourcemod/data/flowdump/<map>.txt
//   flowdump_maps "a,b,c"            dump each map in turn (changelevel after each dump)
//
// File format: "maxflow <float>" then one "<area id> <flow>" line per area (flow -1 = unreachable).
// Local test tool only; never deploy. Needs left4dhooks.
#include <sourcemod>
#include <left4dhooks>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo = { name = "flowdump", author = "Malevolence", description = "Dump nav area flow", version = "1.0", url = "" };

ConVar g_cvMaps, g_cvDelay;

public void OnPluginStart()
{
	g_cvMaps = CreateConVar("flowdump_maps", "", "Comma-separated maps to dump in turn");
	g_cvDelay = CreateConVar("flowdump_delay", "8.0", "Seconds after map start before an automatic dump");
	RegServerCmd("sm_flowdump", Cmd_Dump);
}

public void OnMapStart()
{
	char maps[1024];
	g_cvMaps.GetString(maps, sizeof(maps));
	if (maps[0]) CreateTimer(g_cvDelay.FloatValue, T_Auto, _, TIMER_FLAG_NO_MAPCHANGE);
}

Action Cmd_Dump(int args)
{
	Dump();
	return Plugin_Handled;
}

Action T_Auto(Handle t)
{
	Dump();
	char maps[1024], cur[128], list[32][128];
	g_cvMaps.GetString(maps, sizeof(maps));
	GetCurrentMap(cur, sizeof(cur));
	int n = ExplodeString(maps, ",", list, sizeof(list), sizeof(list[]));
	for (int i = 0; i < n; i++)
	{
		TrimString(list[i]);
		if (!StrEqual(list[i], cur, false)) continue;
		if (i + 1 < n) ServerCommand("changelevel %s", list[i + 1]);
		else { g_cvMaps.SetString(""); PrintToServer("[flowdump] all maps done"); }
		break;
	}
	return Plugin_Stop;
}

void Dump()
{
	char map[128], path[PLATFORM_MAX_PATH];
	GetCurrentMap(map, sizeof(map));
	BuildPath(Path_SM, path, sizeof(path), "data/flowdump");
	if (!DirExists(path)) CreateDirectory(path, 511);
	BuildPath(Path_SM, path, sizeof(path), "data/flowdump/%s.txt", map);
	File f = OpenFile(path, "w");
	if (f == null) { PrintToServer("[flowdump] cannot write %s", path); return; }
	float max = L4D2Direct_GetMapMaxFlowDistance();
	f.WriteLine("maxflow %.1f", max);
	ArrayList areas = new ArrayList();
	L4D_GetAllNavAreas(areas);
	for (int i = 0; i < areas.Length; i++)
	{
		Address a = areas.Get(i);
		f.WriteLine("%d %.1f", L4D_GetNavAreaID(a), L4D2Direct_GetTerrorNavAreaFlow(a));
	}
	delete f;
	PrintToServer("[flowdump] %s: maxflow %.1f, %d areas -> %s", map, max, areas.Length, path);
	delete areas;
}
