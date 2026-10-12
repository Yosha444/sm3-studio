// SPDX-License-Identifier: GPL-3.0-or-later
// Experimental, scoped DX9 draw adapter. No pack/mesh/vertex-shader mutation.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d9.h>
#ifdef VALIDATE_ONLY
#include <mmsystem.h>
#endif
#include <vector>
#include <map>
#include <cstdio>
#include <cstring>
#include "shaders.h"
#include "atlas_signature.h"
#ifndef VALIDATE_ONLY
#include "forwards.h"
#endif

static const GUID marker={0x64506e56,0x5d40,0x49e9,{0xab,0x91,0x44,0x18,0x51,0x01,0xe2,0x03}};
static FILE* logFile=nullptr;
static std::map<IDirect3DDevice9*,IDirect3DTexture9*> atlases;
static IDirect3DTexture9* LoadAtlas(IDirect3DDevice9* dev){
 auto found=atlases.find(dev);if(found!=atlases.end())return found->second;
 atlases[dev]=nullptr;
 wchar_t path[MAX_PATH];GetModuleFileNameW(nullptr,path,MAX_PATH);
 auto slash=wcsrchr(path,L'\\');if(!slash)return nullptr;
 wcscpy_s(slash+1,MAX_PATH-(slash+1-path),L"venom_direct_atlas.tex");
 FILE* f=nullptr;_wfopen_s(&f,path,L"rb");if(!f)return nullptr;
 fseek(f,0,SEEK_END);long length=ftell(f);rewind(f);
 if(length<68||length>100000000){fclose(f);return nullptr;}
 std::vector<BYTE> bytes(length);size_t read=fread(bytes.data(),1,bytes.size(),f);fclose(f);
 if(read!=bytes.size())return nullptr;
 auto hdr=(DWORD*)bytes.data();UINT width=hdr[6],height=hdr[7],levels=hdr[9];
 if(width!=4096||height!=4096||levels!=13||hdr[8]!=1||hdr[10]!=21)return nullptr;
 size_t expected=68;for(UINT l=0;l<levels;l++)expected+=size_t(max(1u,width>>l))*max(1u,height>>l)*4;
 if(expected!=bytes.size())return nullptr;
 IDirect3DTexture9* texture=nullptr;
 if(FAILED(dev->CreateTexture(width,height,levels,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&texture,nullptr)))return nullptr;
 size_t offset=68;
 for(UINT level=0;level<levels;level++){
  UINT w=max(1u,width>>level),h=max(1u,height>>level);D3DLOCKED_RECT rect={};
  if(FAILED(texture->LockRect(level,&rect,nullptr,0))){texture->Release();return nullptr;}
  for(UINT row=0;row<h;row++)memcpy((BYTE*)rect.pBits+row*rect.Pitch,bytes.data()+offset+row*w*4,w*4);
  texture->UnlockRect(level);offset+=size_t(w)*h*4;
 }
 atlases[dev]=texture;return texture;
}
static DWORD HashShader(const std::vector<DWORD>& data){
 DWORD h=2166136261; size_t i=0;
 while(i<data.size()){
  DWORD t=data[i],op=t&65535;
  if(op==65534){i+=1+((t>>16)&32767);continue;}
  size_t n=(i==0||op==65535)?1:1+((t>>24)&15);
  if(i+n>data.size())return 0;
  for(size_t j=i;j<i+n;j++)for(int k=0;k<4;k++)h=(h^((data[j]>>(k*8))&255))*16777619;
  i+=n;
 }
 return h;
}
static bool IsAtlas(IDirect3DBaseTexture9* base){
 if(!base||base->GetType()!=D3DRTYPE_TEXTURE)return false;
 DWORD cached=0,size=4;
 if(SUCCEEDED(base->GetPrivateData(marker,&cached,&size)))return cached==1;
 auto tex=static_cast<IDirect3DTexture9*>(base); D3DSURFACE_DESC d={};
 if(FAILED(tex->GetLevelDesc(0,&d)))return false;
 bool match=false;
 if(d.Width==atlasWidth&&d.Height==atlasHeight&&d.Format==D3DFMT_A8R8G8B8&&d.Pool==D3DPOOL_MANAGED){
  D3DLOCKED_RECT rect={};
  if(SUCCEEDED(tex->LockRect(0,&rect,nullptr,D3DLOCK_READONLY))){
   match=true;
   for(const auto& p:atlasProbes){
    DWORD value=0; memcpy(&value,(BYTE*)rect.pBits+p.y*rect.Pitch+p.x*4,4);
    if(value!=p.bgra){match=false;break;}
   }
   tex->UnlockRect(0);
  }
 }
 cached=match?1:2; base->SetPrivateData(marker,&cached,4,0);
 if(match&&logFile){fprintf(logFile,"ATLAS_MATCH\n");fflush(logFile);}
 return match;
}
struct CachedShader{IDirect3DPixelShader9* original;IDirect3DPixelShader9* replacement;};
static std::map<IDirect3DPixelShader9*,CachedShader> shaderCache;
static IDirect3DPixelShader9* Replacement(IDirect3DDevice9* dev,IDirect3DPixelShader9* original){
 if(!original)return nullptr;
 auto it=shaderCache.find(original); if(it!=shaderCache.end())return it->second.replacement;
 UINT size=0; if(FAILED(original->GetFunction(nullptr,&size))||size%4||size>65536)return nullptr;
 std::vector<DWORD> code(size/4); if(FAILED(original->GetFunction(code.data(),&size)))return nullptr;
 DWORD hash=HashShader(code); IDirect3DPixelShader9* replacement=nullptr;
 for(const auto& entry:shaderEntries)if(entry.signature==hash){dev->CreatePixelShader(entry.code,&replacement);break;}
 original->AddRef(); shaderCache[original]={original,replacement};
 if(logFile){fprintf(logFile,"SHADER %08lX %s\n",hash,replacement?"DIRECT_READY":"UNSUPPORTED_UNCHANGED");fflush(logFile);}
 return replacement;
}
typedef HRESULT (STDMETHODCALLTYPE *DrawFn)(IDirect3DDevice9*,D3DPRIMITIVETYPE,INT,UINT,UINT,UINT,UINT);
static DrawFn originalDraw=nullptr;
static HRESULT STDMETHODCALLTYPE Draw(IDirect3DDevice9* dev,D3DPRIMITIVETYPE type,INT base,UINT min,UINT vertices,UINT start,UINT count){
 IDirect3DBaseTexture9* texture=nullptr; dev->GetTexture(6,&texture);
 bool target=IsAtlas(texture);
 if(!target){if(texture)texture->Release();return originalDraw(dev,type,base,min,vertices,start,count);}
 IDirect3DPixelShader9* original=nullptr; dev->GetPixelShader(&original);
 auto replacement=Replacement(dev,original);
 auto atlas=replacement?LoadAtlas(dev):nullptr;
 if(!replacement||!atlas){if(original)original->Release();texture->Release();return originalDraw(dev,type,base,min,vertices,start,count);}
 const D3DSAMPLERSTATETYPE states[]={D3DSAMP_MINFILTER,D3DSAMP_MAGFILTER,D3DSAMP_MIPFILTER,D3DSAMP_SRGBTEXTURE};
 DWORD saved[4]={};
 for(int i=0;i<4;i++)dev->GetSamplerState(6,states[i],&saved[i]);
 dev->SetPixelShader(replacement);
 dev->SetTexture(6,atlas);
 for(int i=0;i<4;i++)dev->SetSamplerState(6,states[i],i==3?0:D3DTEXF_LINEAR);
 HRESULT hr=originalDraw(dev,type,base,min,vertices,start,count);
 dev->SetPixelShader(original); original->Release();
 dev->SetTexture(6,texture);texture->Release();
 for(int i=0;i<4;i++)dev->SetSamplerState(6,states[i],saved[i]);
 static bool logged=false;if(!logged&&logFile){fprintf(logFile,"DIRECT_DRAW %08lX\n",hr);fflush(logFile);logged=true;}
 return hr;
}
static void* Hook(void* object,size_t slot,void* replacement){
 auto table=*(void***)object;if(table[slot]==replacement)return nullptr;
 DWORD protect; if(!VirtualProtect(&table[slot],sizeof(void*),PAGE_READWRITE,&protect))return nullptr;
 void* original=table[slot]; table[slot]=replacement;
 VirtualProtect(&table[slot],sizeof(void*),protect,&protect);return original;
}
typedef HRESULT (STDMETHODCALLTYPE *CreateDeviceFn)(IDirect3D9*,UINT,D3DDEVTYPE,HWND,DWORD,D3DPRESENT_PARAMETERS*,IDirect3DDevice9**);
static CreateDeviceFn originalDevice=nullptr;
static HRESULT STDMETHODCALLTYPE CreateDevice(IDirect3D9* d,UINT a,D3DDEVTYPE t,HWND w,DWORD flags,D3DPRESENT_PARAMETERS* p,IDirect3DDevice9** result){
 HRESULT hr=originalDevice(d,a,t,w,flags,p,result);
 if(SUCCEEDED(hr)&&result&&*result){if(void* old=Hook(*result,82,(void*)Draw))originalDraw=(DrawFn)old;}
 return hr;
}
typedef IDirect3D9* (WINAPI *Create9Fn)(UINT);
static Create9Fn originalCreate9=nullptr;
static IDirect3D9* WINAPI Create9(UINT sdk){
 if(!logFile){char path[MAX_PATH];GetModuleFileNameA(nullptr,path,MAX_PATH);auto slash=strrchr(path,'\\');if(slash){strcpy_s(slash+1,MAX_PATH-(slash+1-path),"venom_direct.log");fopen_s(&logFile,path,"w");if(logFile){fprintf(logFile,"CREATE9_HOOK_ACTIVE\n");fflush(logFile);}}}
 auto d=originalCreate9(sdk);
 if(d){if(void* old=Hook(d,16,(void*)CreateDevice))originalDevice=(CreateDeviceFn)old;}
 return d;
}
#ifndef VALIDATE_ONLY
// Hook only the game's resolved import. Other proxies continue to receive calls.
static void Install(){
 BYTE* exe=(BYTE*)GetModuleHandleW(nullptr);
 auto dos=(IMAGE_DOS_HEADER*)exe; auto nt=(IMAGE_NT_HEADERS*)(exe+dos->e_lfanew);
 auto dir=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
 if(!dir.VirtualAddress)return;
 auto imports=(IMAGE_IMPORT_DESCRIPTOR*)(exe+dir.VirtualAddress);
 for(;imports->Name;imports++){
  if(_stricmp((char*)exe+imports->Name,"d3d9.dll"))continue;
  // This game's PE omits OriginalFirstThunk and imports only Direct3DCreate9.
  // The installer verifies that on disk. Refuse any multi-entry layout here.
  if(!imports->OriginalFirstThunk){
   auto slot=(IMAGE_THUNK_DATA*)(exe+imports->FirstThunk);
   if(!slot[0].u1.Function||slot[1].u1.Function)return;
   DWORD protection;if(!VirtualProtect(&slot->u1.Function,sizeof(ULONG_PTR),PAGE_READWRITE,&protection))return;
   originalCreate9=(Create9Fn)slot->u1.Function;slot->u1.Function=(ULONG_PTR)Create9;
   VirtualProtect(&slot->u1.Function,sizeof(ULONG_PTR),protection,&protection);return;
  }
  auto names=(IMAGE_THUNK_DATA*)(exe+imports->OriginalFirstThunk);
  auto slots=(IMAGE_THUNK_DATA*)(exe+imports->FirstThunk);
  for(;names->u1.AddressOfData;names++,slots++){
   if(IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))continue;
   auto name=(IMAGE_IMPORT_BY_NAME*)(exe+names->u1.AddressOfData);
   if(strcmp((char*)name->Name,"Direct3DCreate9"))continue;
   DWORD protection;if(!VirtualProtect(&slots->u1.Function,sizeof(ULONG_PTR),PAGE_READWRITE,&protection))return;
   originalCreate9=(Create9Fn)slots->u1.Function; slots->u1.Function=(ULONG_PTR)Create9;
   VirtualProtect(&slots->u1.Function,sizeof(ULONG_PTR),protection,&protection);
  }
 }
}
BOOL WINAPI DllMain(HINSTANCE dll,DWORD reason,LPVOID){
 if(reason==DLL_PROCESS_ATTACH){DisableThreadLibraryCalls(dll);Install();}
 return TRUE;
}
#else
static IDirect3DPixelShader9* expectedShader=nullptr;
static IDirect3DBaseTexture9* expectedTexture=nullptr;
static bool drawChecked=false;
static HRESULT STDMETHODCALLTYPE TestDraw(IDirect3DDevice9* dev,D3DPRIMITIVETYPE,INT,UINT,UINT,UINT,UINT){
 IDirect3DPixelShader9* shader=nullptr;IDirect3DBaseTexture9* texture=nullptr;
 dev->GetPixelShader(&shader);dev->GetTexture(6,&texture);DWORD filter=0;dev->GetSamplerState(6,D3DSAMP_MINFILTER,&filter);
 drawChecked=shader==expectedShader&&texture==expectedTexture&&filter==D3DTEXF_LINEAR;
 if(shader)shader->Release();if(texture)texture->Release();return S_OK;
}
int main(){
 printf("WINMM_FORWARD_OK %lu\n",timeGetTime());
 HWND w=CreateWindowW(L"STATIC",L"Shader validation",WS_OVERLAPPED,0,0,64,64,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
 auto d=Direct3DCreate9(D3D_SDK_VERSION);if(!d)return 1;
 D3DPRESENT_PARAMETERS p={};p.Windowed=TRUE;p.SwapEffect=D3DSWAPEFFECT_DISCARD;p.hDeviceWindow=w;
 IDirect3DDevice9* dev=nullptr;
 HRESULT hr=d->CreateDevice(0,D3DDEVTYPE_HAL,w,D3DCREATE_SOFTWARE_VERTEXPROCESSING,&p,&dev);
 if(FAILED(hr)){printf("DEVICE_FAILED %08lX\n",hr);return 2;}
 for(const auto& entry:shaderEntries){IDirect3DPixelShader9* ps=nullptr;hr=dev->CreatePixelShader(entry.code,&ps);if(FAILED(hr)){printf("SHADER_FAILED %08lX\n",hr);return 3;}ps->Release();if(FAILED(dev->CreatePixelShader(entry.original,&ps)))return 12;if(!Replacement(dev,ps))return 13;printf("SHADER_MATCH_OK %08lX\n",entry.signature);ps->Release();}
 IDirect3DPixelShader9* source=nullptr;
 if(FAILED(dev->CreatePixelShader(native_shader_0,&source)))return 4;
 expectedShader=Replacement(dev,source);if(!expectedShader)return 5;
 expectedTexture=LoadAtlas(dev);if(!expectedTexture)return 6;
 IDirect3DTexture9* target=nullptr;
 if(FAILED(dev->CreateTexture(atlasWidth,atlasHeight,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&target,nullptr)))return 7;
 D3DLOCKED_RECT rect={};if(FAILED(target->LockRect(0,&rect,nullptr,0)))return 8;
 for(UINT y=0;y<atlasHeight;y++)memset((BYTE*)rect.pBits+y*rect.Pitch,0,atlasWidth*4);
 for(const auto& p:atlasProbes)memcpy((BYTE*)rect.pBits+p.y*rect.Pitch+p.x*4,&p.bgra,4);
 target->UnlockRect(0);
 if(!IsAtlas(target))return 9;
 dev->SetPixelShader(source);dev->SetTexture(6,target);dev->SetSamplerState(6,D3DSAMP_MINFILTER,D3DTEXF_POINT);
 originalDraw=TestDraw;Draw(dev,D3DPT_TRIANGLELIST,0,0,3,0,1);if(!drawChecked)return 10;
 IDirect3DPixelShader9* restored=nullptr;IDirect3DBaseTexture9* restoredTexture=nullptr;DWORD filter=0;
 dev->GetPixelShader(&restored);dev->GetTexture(6,&restoredTexture);dev->GetSamplerState(6,D3DSAMP_MINFILTER,&filter);
 if(restored!=source||restoredTexture!=target||filter!=D3DTEXF_POINT)return 11;
 restored->Release();restoredTexture->Release();source->Release();target->Release();
 dev->Release();d->Release();DestroyWindow(w);printf("D3D9_SHADER_MATCH_ATLAS_LOAD_DRAW_SWAP_AND_RESTORE_OK\n");return 0;
}
#endif
