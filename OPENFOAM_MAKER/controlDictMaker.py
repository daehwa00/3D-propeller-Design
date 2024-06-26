def make_controlDict(centroid_x, centroid_y, area, freestream_velocity):
    control_dict_content = f"""/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     | Website:  https://openfoam.org
    \\\\  /    A nd           | Version:  11
     \\\\/     M anipulation  | DAEHWA MADE THIS
\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       dictionary;
    location    "system";
    object      controlDict;
}}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

application     foamRun;

solver          incompressibleFluid;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         200;

deltaT          1;

writeControl    timeStep;

writeInterval   50;

purgeWrite      0;

writeFormat     ascii;

writePrecision  6;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;

functions 
{{
    forceCoeffs 
    {{
        type            forceCoeffs;
        libs ("libforces.so"); // 라이브러리 로드
        writeControl    timeStep;            // 변경: 'outputControl' -> 'writeControl'
        writeInterval   1;                   // 변경: 'outputInterval' -> 'writeInterval'

        patches         ( "walls" );         // 계산할 표면
        pName           p;                   // 압력 필드 이름
        UName           U;                   // 속도 필드 이름
        rho             rhoInf;              // 유체 밀도(비압축성 유동의 경우 'rhoInf'를 사용)
        log             true;                // 로그 파일에 결과 기록
        rhoInf          1.225;               // 유입 유체 밀도 (kg/m^3)
        CofR            ({centroid_x:.2f} {centroid_y:.2f} 0);          // 회전 중심 (x y z)
        pitchAxis       (0 0 1);             // 피치 축 (x y z)

        liftDir         (0 1 0);             // 양력 방향
        dragDir         (1 0 0);             // 항력 방향
        magUInf         {freestream_velocity}; // 유입 속도 (m/s)
        lRef            1;                   // 참조 길이 (m)
        Aref            1;           // 참조 면적 (m^2)
    }}
}}
// 추가: 잔차 기반 종료 조건
residuals
{{
    type            residuals;
    functionObjectLibs ("libutilityFunctionObjects.so");
    outputControl   timeStep;
    outputInterval  1;
    residualControl
    {{
        p               1e-6; // 압력에 대한 잔차 수렴 기준
        U               1e-6; // 속도에 대한 잔차 수렴 기준
    }}
}}
// ************************************************************************* //

    """

    # blockMeshDict 파일 생성
    with open("./controlDict", "w") as f:
        f.write(control_dict_content)
