// SYNTHETIC SAMPLE CODE - not taken from any Conga repository.
using Clm.Api.Services;

namespace Clm.Api
{
    public class Startup
    {
        public void ConfigureServices(IServiceCollection services)
        {
            services.AddScoped<IAgreementService, AgreementService>();
            services.AddScoped<IRenewalService, RenewalService>();
        }
    }
}
